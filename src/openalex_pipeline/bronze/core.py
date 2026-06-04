"""Bronze single-year ingestion: classification and JSONL -> Parquet.

Imports the two leaves (schema, errors). Does NOT import manifest -- ingestion
and derived state are sibling concerns; the runner is the only place that
touches both.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import polars as pl

from .errors import CorruptedState, IntegrityError
from .schema import BRONZE_SCHEMA

_REPORT_NAME = "_YEAR_REPORT.json"


# --- Year classification ----------------------------------------------------


class YearState(Enum):
    """The three states a requested year can be in.

    INGESTED  -- {bronze_root}/{year}.parquet already exists. Skip; never re-read.
    READY     -- extraction marked the year COMPLETE and no bronze Parquet exists.
    PENDING   -- extraction has not completed the year (directory absent, or
                 present without _YEAR_REPORT.json). Skipped; surfaced in manifest.
    """

    INGESTED = "ingested"
    READY = "ready"
    PENDING = "pending"


def classify_year(extract_root: Path, bronze_root: Path, year: int) -> YearState:
    """Classify one year against the extraction and bronze directories.

    Decision order:
      1. {bronze_root}/{year}.parquet exists            -> INGESTED.
      2. {extract_root}/{year}/_YEAR_REPORT.json exists -> READY.
      3. Else                                            -> PENDING.

    The bronze Parquet is checked first by design: an INGESTED year is never
    re-read, so its extraction-side state does not matter.

    Raises:
        CorruptedState: the extraction year directory has _YEAR_REPORT.json but
            zero page-*.jsonl files.
    """
    if _bronze_parquet_path(bronze_root, year).exists():
        return YearState.INGESTED

    if _report_path(extract_root, year).exists():
        if not _page_files(extract_root, year):
            raise CorruptedState(
                f"year {year}: _YEAR_REPORT.json present but no page-*.jsonl files"
            )
        return YearState.READY

    return YearState.PENDING


# --- Single-year ingestion --------------------------------------------------


@dataclass
class YearIngestResult:
    """In-memory outcome of handling one year. Not persisted.

    bronze_row_count and duplicate_id_count are populated only for a freshly
    ingested (READY -> written) year; None for INGESTED and PENDING.

    bronze_file_path is the ABSOLUTE path to {year}.parquet for INGESTED and
    freshly written years; None for PENDING. (The manifest's bronze_file_path
    column is relative to bronze_root -- deliberately a different field for a
    different consumer.)
    """

    year: int
    state: YearState
    bronze_row_count: int | None = None
    duplicate_id_count: int | None = None
    bronze_file_path: Path | None = None


def ingest_year(extract_root: Path, bronze_root: Path, year: int) -> YearIngestResult:
    """Ingest one year to {bronze_root}/{year}.parquet.

    See module/contract docs for the full algorithm. INGESTED and PENDING years
    short-circuit; a READY year is read under BRONZE_SCHEMA, asserted, and
    written atomically.

    Raises:
        IntegrityError: a null `id`, or bronze_row_count != records_fetched.
        CorruptedState: classification ambiguity, a disallowed zero-byte page
            combination, malformed JSONL, or a scalar type mismatch.
    """
    state = classify_year(extract_root, bronze_root, year)
    parquet_path = _bronze_parquet_path(bronze_root, year)

    if state is YearState.INGESTED:
        return YearIngestResult(year, state, bronze_file_path=parquet_path.resolve())
    if state is YearState.PENDING:
        return YearIngestResult(year, state)

    # READY.
    pages = _page_files(extract_root, year)
    empty_pages = [page for page in pages if page.stat().st_size == 0]
    if empty_pages:
        if len(pages) == 1:
            # Zero-result extraction year: a single zero-byte page-0001.jsonl.
            path = write_empty_year(bronze_root, year)
            return YearIngestResult(
                year,
                state,
                bronze_row_count=0,
                duplicate_id_count=0,
                bronze_file_path=path.resolve(),
            )
        raise CorruptedState(
            f"year {year}: zero-byte page file(s) {[p.name for p in empty_pages]} "
            "in a multi-page year -- not a state extraction can produce"
        )

    try:
        frame = (
            pl.scan_ndjson(pages, schema=BRONZE_SCHEMA)
            .select(list(BRONZE_SCHEMA.keys()))
            .collect()
        )
    except pl.exceptions.ComputeError as exc:
        raise CorruptedState(f"year {year}: failed to read page files: {exc}") from exc

    # Integrity assertions over the frame, before any write.
    null_ids = frame.select(pl.col("id").is_null().sum()).item()
    if null_ids:
        raise IntegrityError(f"year {year}: {null_ids} record(s) with null id")

    records_fetched = _load_report(extract_root, year)["records_fetched"]
    if frame.height != records_fetched:
        raise IntegrityError(
            f"year {year}: bronze_row_count {frame.height} != "
            f"records_fetched {records_fetched}"
        )

    duplicate_id_count = frame.height - frame.select(pl.col("id").n_unique()).item()

    _atomic_write_parquet(frame, parquet_path)
    return YearIngestResult(
        year,
        state,
        bronze_row_count=frame.height,
        duplicate_id_count=duplicate_id_count,
        bronze_file_path=parquet_path.resolve(),
    )


def write_empty_year(bronze_root: Path, year: int) -> Path:
    """Write an empty {year}.parquet carrying the full 21-column BRONZE_SCHEMA.

    Used for a zero-result extraction year. Atomic (tmp + rename). Returns the
    written path.
    """
    path = _bronze_parquet_path(bronze_root, year)
    _atomic_write_parquet(pl.DataFrame(schema=BRONZE_SCHEMA), path)
    return path


# --- Internal helpers -------------------------------------------------------


def _bronze_parquet_path(bronze_root: Path, year: int) -> Path:
    return bronze_root / f"{year}.parquet"


def _report_path(extract_root: Path, year: int) -> Path:
    return extract_root / str(year) / _REPORT_NAME


def _page_files(extract_root: Path, year: int) -> list[Path]:
    return sorted((extract_root / str(year)).glob("page-*.jsonl"))


def _load_report(extract_root: Path, year: int) -> dict[str, Any]:
    return json.loads(_report_path(extract_root, year).read_text(encoding="utf-8"))


def _atomic_write_parquet(frame: pl.DataFrame, path: Path) -> None:
    """Write a Parquet via tmp + rename so a file that exists is complete."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    frame.write_parquet(tmp)
    os.replace(tmp, path)
