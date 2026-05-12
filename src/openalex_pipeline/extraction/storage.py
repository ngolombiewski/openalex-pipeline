"""Storage layer: all filesystem mutation lives here.

Concentrates invariants M1 (atomic writes), M2 (_META.json ⟺ first page),
M3 (_CURSOR ⟺ in progress), M5 (cursor staleness bound), M7 (reconciliation),
and M9 (snapshot stamp).

No state of its own; the filesystem itself is the state. Every function
takes `settings` and a `year`, operates on the corresponding year directory,
and returns. Functions are independent and can be called in any valid order
(constrained by what's already on disk).

Test seam: pytest's tmp_path. Tests point settings.output_dir at a tmp
directory and assert on the resulting filesystem state.
"""

from __future__ import annotations

from pathlib import Path

from extraction.config import Settings
from extraction.types import YearMeta


def initialize_year(settings: Settings, year: int, meta: YearMeta) -> None:
    """Write _META.json for a year on its first page fetch.

    Must be called before the first write_page() for a fresh year (M2).
    Idempotent if the existing _META.json matches `meta` exactly; raises
    otherwise.

    Args:
        settings: provides output_dir.
        year: the publication year.
        meta: the YearMeta to record. expected_count comes from the API's
            first response; filter comes from settings.filter; started_at
            is the current UTC time (caller's responsibility).

    Raises:
        ValueError: an existing _META.json disagrees with `meta`. Indicates
            a bug in the runner (initialize_year should only be called
            for fresh years).
    """
    ...


def write_page(
    settings: Settings,
    year: int,
    page_number: int,
    records: list[dict],
    next_cursor: str | None,
) -> None:
    """Write a page to disk and update _CURSOR atomically.

    Sequence (deliberate ordering for M5 self-healing):
    1. Stamp each record with _extracted_at (M9).
    2. Atomically write page_NNNNN.jsonl (M1).
    3. Atomically update _CURSOR to next_cursor (or delete _CURSOR if
       next_cursor is None, marking the year ready for finalize_year).

    Page-write-then-cursor-write order: a crash between steps 2 and 3
    leaves the cursor pointing at the just-written page, causing a benign
    re-fetch on resume (M5). The reverse order would lose data.

    Args:
        settings: provides output_dir.
        year: the publication year directory to write into.
        page_number: 1-indexed page number. Must equal (existing pages + 1);
            the caller (runner) is responsible for tracking this.
        records: the work dicts from the API, without _extracted_at. This
            function injects _extracted_at at write time.
        next_cursor: cursor for the next page, or None if this is the last
            page of the year.

    Raises:
        FileExistsError: page_NNNNN.jsonl already exists. Indicates a bug
            in the runner (page numbering should be monotonic).
        OSError: filesystem error (disk full, permissions, etc.).
    """
    ...


def finalize_year(settings: Settings, year: int) -> None:
    """Run M7 reconciliation; write _SUCCESS iff it passes.

    Counts records across all page_*.jsonl files in the year directory,
    compares to the expected_count in _META.json. On match, writes the
    _SUCCESS marker atomically.

    Args:
        settings: provides output_dir.
        year: the publication year to finalize.

    Raises:
        ReconciliationFailed: M7 violation. _SUCCESS is NOT written.
        FileNotFoundError: _META.json is missing (M2 violation; should not
            happen in normal operation).
    """
    ...


def discard_year(settings: Settings, year: int) -> None:
    """Delete the entire year directory and its contents.

    Used by the runner on M6 drift detection to clear state before
    restarting a year. Idempotent: succeeds (no-op) if the directory
    does not exist.

    Args:
        settings: provides output_dir.
        year: the publication year to discard.

    Raises:
        OSError: filesystem error (permissions, busy file, etc.).
    """
    ...


def read_year_meta(settings: Settings, year: int) -> YearMeta:
    """Load and parse a year's _META.json.

    Args:
        settings: provides output_dir.
        year: the publication year.

    Returns:
        The parsed YearMeta.

    Raises:
        FileNotFoundError: _META.json does not exist for this year.
        ValueError: _META.json is malformed (missing fields, bad types).
    """
    ...


def read_cursor(settings: Settings, year: int) -> str:
    """Load a year's _CURSOR file.

    Args:
        settings: provides output_dir.
        year: the publication year.

    Returns:
        The cursor string. Whitespace stripped.

    Raises:
        FileNotFoundError: _CURSOR does not exist for this year.
    """
    ...


def count_pages_on_disk(settings: Settings, year: int) -> int:
    """Count page_*.jsonl files for a year. Does not read their contents.

    Used by scan() to determine the resume page number. Validates M4
    (contiguous page numbering) and raises CorruptedYearState on gaps.

    Args:
        settings: provides output_dir.
        year: the publication year.

    Returns:
        The number of page files present. 0 if the directory is empty
        or does not exist.

    Raises:
        CorruptedYearState: M4 violation (gap in page numbering).
    """
    ...


# --- Private helpers (encode specific invariants) ---


def _atomic_write_bytes(path: Path, data: bytes) -> None:
    """Write bytes to path atomically via tmp + os.replace (M1).

    Sequence:
    1. Write data to a sibling .tmp file.
    2. os.replace(tmp, path) — atomic on POSIX within one filesystem.

    fsync is omitted by design: protects against process crashes (common)
    but not power loss (rare, recoverable by re-running).

    Args:
        path: final destination path.
        data: bytes to write.

    Raises:
        OSError: filesystem error.
    """
    ...


def _stamp_records(records: list[dict], extracted_at_iso: str) -> list[dict]:
    """Inject the _extracted_at field into each record (M9).

    Returns a new list with new dicts; does not mutate the input.

    Args:
        records: list of work dicts from the API.
        extracted_at_iso: ISO 8601 UTC timestamp string.

    Returns:
        New list of dicts, each with _extracted_at added.
    """
    ...


def _year_dir(settings: Settings, year: int) -> Path:
    """Construct the path to a year directory."""
    ...
