"""Storage layer: all filesystem I/O for the extraction module.

The filesystem is the source of truth. The worker knows only pages, the cursor,
and abstract year state; it never touches files directly. Five public functions
form the entire contract:

    classify_year    -- read disk, return the year's state (+ resume pointer)
    initialize_year  -- create a fresh year directory's metadata
    write_page       -- persist one page + advance the cursor
    finalize_year    -- write and return the completion report
    read_year_report -- read and return the completion report (skip path)

All five take ``root: Path, year: int`` as their first two arguments.

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

import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .exceptions import CorruptedState, QueryMismatch
from .models import YearReport, YearState, YearStatus

_META_FILE = "_META.json"
_CURSOR_FILE = "_CURSOR.json"
_REPORT_FILE = "_YEAR_REPORT.json"
_PAGE_GLOB = "page-*.jsonl"


def _year_dir(root: Path, year: int) -> Path:
    return root / str(year)


def _page_path(year_dir: Path, page_number: int) -> Path:
    return year_dir / f"page-{page_number:04d}.jsonl"


def _list_pages(year_dir: Path) -> list[Path]:
    return sorted(year_dir.glob(_PAGE_GLOB))


def _now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def _atomic_write_json(path: Path, obj: object) -> None:
    _atomic_write_bytes(path, json.dumps(obj).encode("utf-8"))


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        raise CorruptedState(f"could not read {path}: {exc}") from exc


def _count_lines(path: Path) -> int:
    return path.read_bytes().count(b"\n")


def _inspect_layout(year_dir: Path) -> set[str]:
    """Return which recognized markers exist in the year directory.

    Subset of {"meta", "cursor", "report", "pages"}. Empty set means the
    directory is missing or holds none of the four. Unrecognized files are
    ignored (the module does not guard against external tampering).
    """
    if not year_dir.exists():
        return set()
    present: set[str] = set()
    if (year_dir / _META_FILE).is_file():
        present.add("meta")
    if (year_dir / _CURSOR_FILE).is_file():
        present.add("cursor")
    if (year_dir / _REPORT_FILE).is_file():
        present.add("report")
    if any(year_dir.glob(_PAGE_GLOB)):
        present.add("pages")
    return present


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
    year_dir = _year_dir(root, year)
    layout = _inspect_layout(year_dir)

    if not layout:
        return YearStatus(state=YearState.FRESH)

    # _YEAR_REPORT.json is the authoritative completion signal; it wins over
    # any other files present (stale cursor, etc.).
    if "report" in layout:
        report = _read_json(year_dir / _REPORT_FILE)
        if report.get("query") != query:
            raise QueryMismatch(
                f"year {year}: stored query {report.get('query')!r} "
                f"!= current query {query!r}"
            )
        return YearStatus(state=YearState.COMPLETE)

    if layout == {"meta", "cursor", "pages"}:
        meta = _read_json(year_dir / _META_FILE)
        if meta.get("query") != query:
            raise QueryMismatch(
                f"year {year}: stored query {meta.get('query')!r} "
                f"!= current query {query!r}"
            )
        cursor_doc = _read_json(year_dir / _CURSOR_FILE)
        next_page = cursor_doc.get("next_page")
        if not isinstance(next_page, int):
            raise CorruptedState(
                f"year {year}: _CURSOR.json next_page invalid: {next_page!r}"
            )
        cursor = cursor_doc.get("cursor")
        if cursor is not None and not isinstance(cursor, str):
            raise CorruptedState(
                f"year {year}: _CURSOR.json cursor invalid: {cursor!r}"
            )
        return YearStatus(
            state=YearState.IN_PROGRESS,
            cursor=cursor,
            next_page=next_page,
        )

    raise CorruptedState(
        f"year {year}: invalid file combination: {sorted(layout)!r}"
    )


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
    year_dir = _year_dir(root, year)
    _atomic_write_json(
        year_dir / _META_FILE,
        {
            "query": query,
            "expected_count": meta_count,
            "started_at": _now_utc(),
        },
    )
    _atomic_write_json(
        year_dir / _CURSOR_FILE,
        {"cursor": "*", "next_page": 1},
    )


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
    year_dir = _year_dir(root, year)
    payload = b"".join(json.dumps(r).encode("utf-8") + b"\n" for r in records)
    _atomic_write_bytes(_page_path(year_dir, page_number), payload)
    _atomic_write_json(
        year_dir / _CURSOR_FILE,
        {"cursor": next_cursor, "next_page": page_number + 1},
    )


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
    year_dir = _year_dir(root, year)
    meta = _read_json(year_dir / _META_FILE)
    pages = _list_pages(year_dir)
    records_fetched = sum(_count_lines(p) for p in pages)
    expected_count = meta["expected_count"]
    report = YearReport(
        query=meta["query"],
        year=year,
        started_at=meta["started_at"],
        completed_at=_now_utc(),
        expected_count=expected_count,
        records_fetched=records_fetched,
        page_count=len(pages),
        count_mismatch=records_fetched != expected_count,
    )
    _atomic_write_json(
        year_dir / _REPORT_FILE,
        {
            "query": report.query,
            "year": report.year,
            "started_at": report.started_at,
            "completed_at": report.completed_at,
            "expected_count": report.expected_count,
            "records_fetched": report.records_fetched,
            "page_count": report.page_count,
            "count_mismatch": report.count_mismatch,
        },
    )
    return report


def read_year_report(root: Path, year: int) -> YearReport:
    """Read _YEAR_REPORT.json and return it as a YearReport.

    Called by the worker on the COMPLETE skip path to hydrate the YearOutcome
    for a year that completed in a previous invocation. Pairs with
    finalize_year (write/read symmetry).

    Precondition: the year is COMPLETE (callers already classified it).

    Returns:
        YearReport: parsed from _YEAR_REPORT.json verbatim.
    """
    data = _read_json(_year_dir(root, year) / _REPORT_FILE)
    return YearReport(
        query=data["query"],
        year=data["year"],
        started_at=data["started_at"],
        completed_at=data["completed_at"],
        expected_count=data["expected_count"],
        records_fetched=data["records_fetched"],
        page_count=data["page_count"],
        count_mismatch=data["count_mismatch"],
    )
