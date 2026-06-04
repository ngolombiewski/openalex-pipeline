"""Bronze manifest: derived, never authoritative.

Rebuilt wholesale from on-disk state every run. Imports the two leaves (schema,
errors) but NOT core: the manifest re-derives each year's status directly from
the filesystem rather than reusing core.classify_year, keeping ingestion and
derived state decoupled (they are siblings; only the runner touches both). The
status strings it emits match core.YearState's values by contract.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

_REPORT_NAME = "_YEAR_REPORT.json"

MANIFEST_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "publication_year": pl.Int64,
    "status": pl.String,
    "query": pl.String,
    "expected_count": pl.Int64,
    "records_fetched": pl.Int64,
    "count_mismatch": pl.Boolean,
    "extraction_completed_at": pl.String,
    "bronze_row_count": pl.Int64,
    "duplicate_id_count": pl.Int64,
    "bronze_file_path": pl.String,
    "ingested_at": pl.Datetime("us", "UTC"),
}
"""Column order and dtypes of the manifest. ingested_at is a UTC datetime
derived from the Parquet's mtime."""


def build_manifest(extract_root: Path, bronze_root: Path, years: list[int]) -> pl.DataFrame:
    """Build the manifest DataFrame: one row per year in `years`.

    The manifest is derived and never authoritative: it is rebuilt wholesale
    from on-disk state. `years` scopes the manifest exactly -- no more, no fewer
    rows. See the contract for per-column semantics.
    """
    rows = [_year_row(extract_root, bronze_root, year) for year in years]
    return pl.DataFrame(rows, schema=MANIFEST_SCHEMA, orient="row")


def write_manifest(bronze_root: Path, manifest: pl.DataFrame) -> Path:
    """Write the manifest to {bronze_root}/_MANIFEST.parquet (atomic). Returns path."""
    path = bronze_root / "_MANIFEST.parquet"
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    manifest.write_parquet(tmp)
    os.replace(tmp, path)
    return path


# --- Internal ---------------------------------------------------------------

def _year_row(extract_root: Path, bronze_root: Path, year: int) -> dict[str, Any]:
    parquet = bronze_root / f"{year}.parquet"
    report_path = extract_root / str(year) / _REPORT_NAME

    report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None

    if parquet.exists():
        status = "ingested"
    elif report is not None:
        status = "ready"
    else:
        status = "pending"

    row: dict[str, Any] = {
        "publication_year": year,
        "status": status,
        "query": None,
        "expected_count": None,
        "records_fetched": None,
        "count_mismatch": None,
        "extraction_completed_at": None,
        "bronze_row_count": None,
        "duplicate_id_count": None,
        "bronze_file_path": None,
        "ingested_at": None,
    }

    if report is not None:
        row["query"] = report.get("query")
        row["expected_count"] = report.get("expected_count")
        row["records_fetched"] = report.get("records_fetched")
        row["count_mismatch"] = report.get("count_mismatch")
        row["extraction_completed_at"] = report.get("completed_at")

    if parquet.exists():
        ids = pl.read_parquet(parquet, columns=["id"])
        row["bronze_row_count"] = ids.height
        row["duplicate_id_count"] = ids.height - ids.select(pl.col("id").n_unique()).item()
        row["bronze_file_path"] = f"{year}.parquet"  # relative to bronze_root
        row["ingested_at"] = datetime.fromtimestamp(parquet.stat().st_mtime, tz=timezone.utc)

    return row
