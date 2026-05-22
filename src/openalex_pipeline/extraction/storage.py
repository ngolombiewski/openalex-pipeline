"""Storage layer: all filesystem I/O for the extraction module.

The filesystem is the source of truth. The worker knows only pages, the cursor,
and abstract year state; it never touches files directly. Four public functions
form the entire contract:

    classify_year    -- read disk, return the year's state (+ resume pointer)
    initialize_year  -- create a fresh year directory's metadata
    write_page       -- persist one page + advance the cursor
    finalize_year    -- write and return the completion report

All four take ``root: Path, year: int`` as their first two arguments.

On-disk layout for one year::

    {root}/{year}/
      _META.json          immutable; written first for a fresh year
      _CURSOR.json        mutable resume pointer; rewritten by every write_page
      page-0001.jsonl     one file per API page
      page-0002.jsonl
      ...
      _YEAR_REPORT.json   written last; its presence == year complete

INTERNAL HELPERS (not part of the contract, prefixed ``_``): atomic write
(tmp + flush + rename, no fsync), page-file path construction, JSON read/write,
line counting. Their existence and signatures are an implementation detail.

INVARIANTS enforced here:
  - _META.json and _YEAR_REPORT.json are immutable once written.
  - Atomic writes for every file (tmp + flush + rename).
  - write_page always writes a page file, even for an empty page (a zero-byte
    file), so ">=1 page file for any non-fresh year" always holds.
  - Any file combination that is not FRESH / IN_PROGRESS / COMPLETE -> raise
    CorruptedState. No silent recovery.
"""

from __future__ import annotations

from pathlib import Path

from .models import YearReport, YearStatus


def classify_year(root: Path, year: int, query: str) -> YearStatus:
    """Classify the year directory and, for non-fresh years, verify the query.

    Disk conditions:
      - FRESH        -- directory missing or empty.
      - IN_PROGRESS  -- _META.json + _CURSOR.json + >=1 page file, and no
                        _YEAR_REPORT.json.
      - COMPLETE     -- _YEAR_REPORT.json present.

    For any non-fresh year, the stored query is compared to ``query``:
    ``_META.query`` for IN_PROGRESS, ``_YEAR_REPORT.query`` for COMPLETE.

    Returns:
        YearStatus. For IN_PROGRESS, ``cursor`` and ``next_page`` are populated
        from _CURSOR.json; ``cursor`` may be None (finalize-pending sub-state).
        For FRESH and COMPLETE, both are None.

    Raises:
        QueryMismatch:   non-fresh year whose stored query != query.
        CorruptedState:  any other file combination, or a structurally invalid
                         _META.json / _CURSOR.json needed for IN_PROGRESS.
    """
    raise NotImplementedError


def initialize_year(root: Path, year: int, query: str, meta_count: int) -> None:
    """Create the metadata for a fresh year, before any page is written.

    Writes, in order:
      1. _META.json -- {query, expected_count: meta_count, started_at: <now>}.
         ``started_at`` is an ISO 8601 UTC string generated here.
      2. _CURSOR.json -- {cursor: "*", next_page: 1}.

    Precondition: the year is FRESH. Called only after the first ``fetch_page``
    has succeeded (so a fetch failure leaves nothing on disk to clean up).

    Returns:
        None.
    """
    raise NotImplementedError


def write_page(
    root: Path,
    year: int,
    records: list[dict],
    next_cursor: str | None,
    page_number: int,
) -> None:
    """Persist one page and advance the cursor. Write-only: reads nothing.

    Writes, in order:
      1. page-{page_number:04d}.jsonl -- one JSON object per line, one line per
         record. An empty ``records`` list produces a zero-byte file (not
         "[]", not a blank line).
      2. _CURSOR.json -- overwritten with {cursor: next_cursor, next_page:
         page_number + 1}. ``next_cursor`` of None is persisted as JSON null.

    ``page_number`` is supplied by the worker (its loop induction variable);
    this function never reads _CURSOR.json to discover it. The fixed write
    order (page first, cursor second) is what makes resume idempotent: a crash
    between the two writes simply causes the page to be re-fetched and
    overwritten on the next run.

    Does not branch on ``len(records)``.

    Returns:
        None.
    """
    raise NotImplementedError


def finalize_year(root: Path, year: int) -> YearReport:
    """Write _YEAR_REPORT.json, marking the year complete.

    Reads _META.json (for ``query``, ``expected_count``, ``started_at``),
    counts lines across every page-*.jsonl file, and writes _YEAR_REPORT.json::

        {query, year, started_at, completed_at, expected_count,
         records_fetched, page_count, count_mismatch}

    ``completed_at`` is an ISO 8601 UTC string generated here. ``count_mismatch``
    is ``records_fetched != expected_count`` -- recorded, never blocking.

    Precondition: all pages have been written (the worker calls this after the
    fetch loop ends, i.e. once ``next_cursor`` came back None).

    Returns:
        YearReport: the same report written to _YEAR_REPORT.json.
    """
    raise NotImplementedError
