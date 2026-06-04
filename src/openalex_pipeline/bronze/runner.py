"""Bronze runner: ingest every READY year, then rebuild the manifest.

The only module that touches both core (ingestion) and manifest (derived state).
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from .core import ingest_year
from .manifest import build_manifest, write_manifest


def run(extract_root: Path, bronze_root: Path, years: list[int]) -> pl.DataFrame:
    """Ingest every READY year in `years`, then rebuild and write the manifest.

    ingest_year classifies internally and short-circuits INGESTED/PENDING years,
    so this is just a loop. CorruptedState and IntegrityError propagate -- bronze
    fails loud and the run stops. `years` scopes both ingestion and the manifest.
    Idempotent: re-running re-classifies done years as INGESTED and skips them.
    """
    for year in years:
        ingest_year(extract_root, bronze_root, year)

    manifest = build_manifest(extract_root, bronze_root, years)
    write_manifest(bronze_root, manifest)
    return manifest
