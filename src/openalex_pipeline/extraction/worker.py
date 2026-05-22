"""Year worker: paginates a single year shard.

``process_year`` is where the real work happens. It is a pure state machine
over one year directory; it knows pages, the cursor, and abstract state, and
delegates every filesystem touch to ``storage`` and every API call to an
injected ``fetch_page``.

The pinned loop (do not deviate)::

    status = classify_year(root, year, query)

    if status.state is COMPLETE:
        return <skipped outcome>

    if status.state is FRESH:
        records, next_cursor, meta_count = fetch_page(query, "*", api_key)
        initialize_year(root, year, query, meta_count)
        write_page(root, year, records, next_cursor, page_number=1)
        cursor, page_number = next_cursor, 2
    else:  # IN_PROGRESS  (cursor may already be None: finalize-pending)
        cursor, page_number = status.cursor, status.next_page

    while cursor is not None:
        records, next_cursor, _ = fetch_page(query, cursor, api_key)
        write_page(root, year, records, next_cursor, page_number)
        cursor, page_number = next_cursor, page_number + 1

    report = finalize_year(root, year)
    return <completed outcome carrying report>

Key points:
  - Fresh-path order is fixed: fetch_page -> initialize_year -> write_page, so a
    first-fetch failure leaves nothing on disk.
  - ``page_number`` is an in-memory induction variable, seeded by classify_year
    and incremented locally. write_page is handed it; it is never re-read.
  - An IN_PROGRESS year with ``cursor is None`` skips the while loop entirely
    and goes straight to finalize_year (the finalize-pending sub-state).
  - DailyLimitReached / RetryExhausted / NonRetryableError from fetch_page
    propagate untouched. The runner catches DailyLimitReached to return a
    partial run report. The fixed write order guarantees _CURSOR.json is
    consistent whenever a fetch raises.
"""

from __future__ import annotations

from pathlib import Path
from typing import Callable

from loguru import logger

from . import storage
from .models import YearOutcome, YearState

# Signature of the injected connector: (query, cursor, api_key) -> (records,
# next_cursor, meta_count). See connector.fetch_page.
FetchPage = Callable[[str, str, str], "tuple[list[dict], str | None, int]"]


def process_year(
    root: Path,
    year: int,
    query: str,
    api_key: str,
    fetch_page: FetchPage,
) -> YearOutcome:
    """Bring a single year shard to COMPLETE, resuming if already in progress.

    Args:
        root:       Extraction root directory.
        year:       Calendar year to process.
        query:      Run query (host- and key-free), passed to classify_year
                    for the isolation check and to fetch_page for each request.
        api_key:    OpenAlex API key, forwarded to fetch_page.
        fetch_page: Injected connector callable (see module docstring).

    Returns:
        YearOutcome -- distinguishes "skipped (already complete)" from
        "completed this run" and carries the persisted year report. The worker
        itself keeps no running counters; all report data comes from
        _YEAR_REPORT.json.

    Raises:
        QueryMismatch, CorruptedState:        from classify_year.
        DailyLimitReached, RetryExhausted,
        NonRetryableError:                          from fetch_page, propagated.
    """
    status = storage.classify_year(root, year, query)

    if status.state is YearState.COMPLETE:
        logger.info("year {} already complete; reading persisted report", year)
        return YearOutcome(
            year=year,
            status="skipped",
            report=storage.read_year_report(root, year),
        )

    if status.state is YearState.FRESH:
        logger.info("year {} is fresh; fetching first page", year)
        records, next_cursor, meta_count = fetch_page(query, "*", api_key)
        storage.initialize_year(root, year, query, meta_count)
        storage.write_page(root, year, records, next_cursor, 1)
        logger.info(
            "year {} page {} written: records={} next_cursor={}",
            year,
            1,
            len(records),
            next_cursor is not None,
        )
        cursor, page_number = next_cursor, 2
    else:  # IN_PROGRESS; next_page is guaranteed populated by classify_year.
        assert status.next_page is not None
        cursor, page_number = status.cursor, status.next_page
        if cursor is None:
            logger.info("year {} is finalize-pending; no fetch needed", year)
        else:
            logger.info("year {} is in progress; resuming at page {}", year, page_number)

    while cursor is not None:
        records, next_cursor, _ = fetch_page(query, cursor, api_key)
        storage.write_page(root, year, records, next_cursor, page_number)
        logger.info(
            "year {} page {} written: records={} next_cursor={}",
            year,
            page_number,
            len(records),
            next_cursor is not None,
        )
        cursor, page_number = next_cursor, page_number + 1

    logger.info("year {} finalizing", year)
    return YearOutcome(
        year=year,
        status="completed",
        report=storage.finalize_year(root, year),
    )
