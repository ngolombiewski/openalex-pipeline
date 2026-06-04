"""Tests for bronze.manifest: build_manifest, write_manifest.

Covers the M-series in docs/bronze-tests.md.
"""

from __future__ import annotations

import os


from openalex_pipeline.bronze.core import ingest_year
from openalex_pipeline.bronze.manifest import build_manifest, write_manifest

from .conftest import (
    make_extract_year,
    make_record,
    manifest_row,
    read_manifest,
    tmp_files,
)


def test_one_row_per_requested_year(extract_root, bronze_root):
    # M1: exactly one row per requested year, regardless of other on-disk state.
    make_extract_year(extract_root, 2000, records=[make_record("W1")])
    ingest_year(extract_root, bronze_root, 2000)
    # A year present on disk but NOT in the request must not leak in.
    make_extract_year(extract_root, 1999, records=[make_record("W9")])
    ingest_year(extract_root, bronze_root, 1999)

    manifest = build_manifest(extract_root, bronze_root, [2000, 2001, 2002])

    assert manifest.height == 3
    assert sorted(manifest["publication_year"].to_list()) == [2000, 2001, 2002]


def test_ingested_row_fully_populated(extract_root, bronze_root):
    # M2: status + extraction fields forwarded + bronze-side fields computed.
    records = [make_record("W1"), make_record("W2")]
    make_extract_year(
        extract_root,
        2002,
        records=records,
        report={
            "query": "works?filter=...:2002",
            "expected_count": 2,
            "records_fetched": 2,
            "count_mismatch": False,
            "completed_at": "2026-05-22T22:52:46Z",
        },
    )
    ingest_year(extract_root, bronze_root, 2002)

    row = manifest_row(build_manifest(extract_root, bronze_root, [2002]), 2002)

    assert row["status"] == "ingested"
    # Extraction-side, forwarded verbatim.
    assert row["query"] == "works?filter=...:2002"
    assert row["expected_count"] == 2
    assert row["records_fetched"] == 2
    assert row["count_mismatch"] is False
    assert row["extraction_completed_at"] == "2026-05-22T22:52:46Z"
    # Bronze-side, computed from the Parquet.
    assert row["bronze_row_count"] == 2
    assert row["duplicate_id_count"] == 0
    assert row["bronze_file_path"] is not None
    assert row["ingested_at"] is not None


def test_pending_row_has_nulls(extract_root, bronze_root):
    # M3: no report -> both bronze-side and extraction-side columns null.
    make_extract_year(extract_root, 2002, complete=False)

    row = manifest_row(build_manifest(extract_root, bronze_root, [2002]), 2002)

    assert row["status"] == "pending"
    for column in ("bronze_row_count", "duplicate_id_count", "bronze_file_path", "ingested_at"):
        assert row[column] is None
    for column in ("query", "expected_count", "records_fetched", "extraction_completed_at"):
        assert row[column] is None


def test_ready_row_representable(extract_root, bronze_root):
    # M4 (G2): READY at build time (report present, not yet ingested).
    make_extract_year(extract_root, 2002, records=[make_record("W1")])

    row = manifest_row(build_manifest(extract_root, bronze_root, [2002]), 2002)

    assert row["status"] == "ready"
    # Extraction-side known, bronze-side not yet.
    assert row["records_fetched"] == 1
    assert row["bronze_row_count"] is None
    assert row["ingested_at"] is None


def test_count_mismatch_forwarded_verbatim(extract_root, bronze_root):
    # M5: non-blocking flag forwarded, no raise.
    make_extract_year(
        extract_root, 2002, records=[make_record("W1")], report={"count_mismatch": True}
    )
    ingest_year(extract_root, bronze_root, 2002)

    row = manifest_row(build_manifest(extract_root, bronze_root, [2002]), 2002)
    assert row["count_mismatch"] is True


def test_bronze_row_count_equals_records_fetched_when_ingested(extract_root, bronze_root):
    # M6: the divergence case is a loud IntegrityError at ingestion (test_core
    # C20), so any written year necessarily has bronze_row_count ==
    # records_fetched. The manifest records both for visibility; build_manifest
    # does not re-check or raise.
    make_extract_year(extract_root, 2002, records=[make_record("W1"), make_record("W2")])
    ingest_year(extract_root, bronze_root, 2002)

    row = manifest_row(build_manifest(extract_root, bronze_root, [2002]), 2002)
    assert row["bronze_row_count"] == row["records_fetched"] == 2


def test_ingested_at_derives_from_parquet_mtime(extract_root, bronze_root):
    # M7: ingested_at reflects the file mtime, not "now".
    make_extract_year(extract_root, 2002, records=[make_record("W1")])
    ingest_year(extract_root, bronze_root, 2002)
    parquet = bronze_root / "2002.parquet"

    # Pin the mtime to a known past instant.
    past = 1_500_000_000  # 2017-07-14 UTC
    os.utime(parquet, (past, past))

    row = manifest_row(build_manifest(extract_root, bronze_root, [2002]), 2002)

    # Compare against the file's own mtime, dtype-agnostically: the manifest's
    # ingested_at must correspond to `past`, not the wall clock.
    ingested_at = row["ingested_at"]
    assert ingested_at is not None
    # The value, whatever its dtype, must round to the pinned epoch second.
    epoch_seconds = ingested_at.timestamp() if hasattr(ingested_at, "timestamp") else float(ingested_at)
    assert int(epoch_seconds) == past


def test_ingested_at_stable_across_rebuilds(extract_root, bronze_root):
    # M8: rebuilding the manifest without touching the parquet never re-stamps.
    make_extract_year(extract_root, 2002, records=[make_record("W1")])
    ingest_year(extract_root, bronze_root, 2002)

    first = manifest_row(build_manifest(extract_root, bronze_root, [2002]), 2002)
    second = manifest_row(build_manifest(extract_root, bronze_root, [2002]), 2002)

    assert first["ingested_at"] == second["ingested_at"]


def test_bronze_file_path_is_relative_to_bronze_root(extract_root, bronze_root):
    # M9 (G3): manifest column is the relative string "{year}.parquet".
    make_extract_year(extract_root, 2002, records=[make_record("W1")])
    ingest_year(extract_root, bronze_root, 2002)

    row = manifest_row(build_manifest(extract_root, bronze_root, [2002]), 2002)
    assert row["bronze_file_path"] == "2002.parquet"


def test_write_manifest_roundtrips_and_overwrites(extract_root, bronze_root):
    # M10
    make_extract_year(extract_root, 2002, records=[make_record("W1")])
    ingest_year(extract_root, bronze_root, 2002)
    manifest = build_manifest(extract_root, bronze_root, [2002])

    path = write_manifest(bronze_root, manifest)
    assert path == (bronze_root / "_MANIFEST.parquet")
    assert tmp_files(bronze_root) == []

    reread = read_manifest(bronze_root)
    assert reread.sort("publication_year").equals(manifest.sort("publication_year"))

    # Overwrites wholesale: a second, narrower manifest replaces the first.
    smaller = build_manifest(extract_root, bronze_root, [2002])
    write_manifest(bronze_root, smaller)
    assert read_manifest(bronze_root).height == smaller.height
