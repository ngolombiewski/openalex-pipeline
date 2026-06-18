"""Bronze runner: ingest every READY year, then rebuild the manifest.

The only module that touches both core (ingestion) and manifest (derived state).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl
from loguru import logger

from .core import YearIngestResult, YearState, assert_query_homogeneity, ingest_year
from .manifest import build_manifest, write_manifest


def run(extract_root: Path, bronze_root: Path, years: list[int]) -> pl.DataFrame:
    """Ingest every READY year in `years`, then rebuild and write the manifest.

    Pre-flight: assert_query_homogeneity over the years in scope (one landing
    zone = one query) -- a mixed corpus raises IntegrityError before a single
    shard is ingested. Then ingest_year classifies internally and
    short-circuits INGESTED/PENDING years, so this is just a loop. Each year is
    logged the moment it is processed, so progress is visible live rather than
    only in a summary at the end. CorruptedState and IntegrityError propagate
    -- bronze fails loud and the run stops. `years` scopes both ingestion and
    the manifest. Idempotent: re-running re-classifies done years as INGESTED
    and skips them.
    """
    assert_query_homogeneity(extract_root, years)
    for year in years:
        result = ingest_year(extract_root, bronze_root, year)
        _log_year(result)

    manifest = build_manifest(extract_root, bronze_root, years)
    path = write_manifest(bronze_root, manifest)
    logger.info(f"manifest written: {path} ({len(years)} year(s))")
    return manifest


# --- Internal ---------------------------------------------------------------

def _log_year(result: YearIngestResult) -> None:
    """Log one year's outcome live, surfacing non-blocking warnings (smoke alarms).

    A freshly written year reports "ingested (bronze_row_count=N)". A year that
    was already done is reported "ingested (skipped)" -- its parquet is never
    re-read, so no row count. PENDING years report "pending (skipped)".
    """
    year = result.year
    if result.state is YearState.INGESTED:
        logger.info(f"{year}: ingested (skipped)")
    elif result.state is YearState.PENDING:
        logger.info(f"{year}: pending (skipped)")
    else:
        logger.info(f"{year}: ingested (bronze_row_count={result.bronze_row_count})")

    if result.duplicate_id_count:
        logger.warning(
            f"{year}: {result.duplicate_id_count} duplicate id(s) in bronze "
            "(non-blocking; cause may be source churn or disk corruption)"
        )
    if result.count_mismatch:
        logger.warning(
            f"{year}: extraction reported count_mismatch (non-blocking)"
        )
