"""Tests for bronze.runner: run.

Covers the R-series in docs/bronze-tests.md.
"""

from __future__ import annotations

import pytest

from openalex_pipeline.bronze.errors import CorruptedState, IntegrityError
from openalex_pipeline.bronze.runner import run

from .conftest import (
    corrupt_page_line,
    make_extract_year,
    make_record,
    manifest_row,
    read_manifest,
)


def test_run_ingests_range_and_writes_manifest(extract_root, bronze_root):
    # R1
    make_extract_year(extract_root, 2001, records=[make_record("W1")])
    make_extract_year(extract_root, 2002, records=[make_record("W2")])

    manifest = run(extract_root, bronze_root, [2001, 2002])

    assert (bronze_root / "2001.parquet").exists()
    assert (bronze_root / "2002.parquet").exists()
    assert (bronze_root / "_MANIFEST.parquet").exists()
    assert sorted(manifest["publication_year"].to_list()) == [2001, 2002]


def test_run_handles_mixed_states(extract_root, bronze_root):
    # R2: one READY, one already-INGESTED, one PENDING.
    make_extract_year(extract_root, 2000, records=[make_record("W0")])
    run(extract_root, bronze_root, [2000])  # 2000 now INGESTED

    make_extract_year(extract_root, 2001, records=[make_record("W1")])  # READY
    make_extract_year(extract_root, 2002, complete=False)               # PENDING

    manifest = run(extract_root, bronze_root, [2000, 2001, 2002])

    assert manifest_row(manifest, 2000)["status"] == "ingested"
    assert manifest_row(manifest, 2001)["status"] == "ingested"
    assert manifest_row(manifest, 2002)["status"] == "pending"
    assert (bronze_root / "2001.parquet").exists()
    assert not (bronze_root / "2002.parquet").exists()


def test_manifest_scoped_to_requested_years(extract_root, bronze_root):
    # R3: ingested years outside `years` do not appear (Invariant 6).
    make_extract_year(extract_root, 2000, records=[make_record("W0")])
    make_extract_year(extract_root, 2001, records=[make_record("W1")])
    run(extract_root, bronze_root, [2000, 2001])

    manifest = run(extract_root, bronze_root, [2001])

    assert manifest["publication_year"].to_list() == [2001]


def test_rerun_is_idempotent(extract_root, bronze_root):
    # R4: second run reclassifies done years INGESTED, does not rewrite.
    make_extract_year(extract_root, 2001, records=[make_record("W1")])
    make_extract_year(extract_root, 2002, records=[make_record("W2")])

    first = run(extract_root, bronze_root, [2001, 2002])
    mtimes = {y: (bronze_root / f"{y}.parquet").stat().st_mtime_ns for y in (2001, 2002)}

    second = run(extract_root, bronze_root, [2001, 2002])

    for year in (2001, 2002):
        assert (bronze_root / f"{year}.parquet").stat().st_mtime_ns == mtimes[year]
        assert manifest_row(first, year)["ingested_at"] == manifest_row(second, year)["ingested_at"]


def test_catch_up_equals_range_ingest(extract_root, bronze_root):
    # R5: a year that becomes READY between runs is picked up; the other untouched.
    make_extract_year(extract_root, 2001, records=[make_record("W1")])
    make_extract_year(extract_root, 2002, complete=False)  # PENDING initially

    run(extract_root, bronze_root, [2001, 2002])
    assert not (bronze_root / "2002.parquet").exists()
    mtime_2001 = (bronze_root / "2001.parquet").stat().st_mtime_ns

    # 2002 completes.
    make_extract_year(extract_root, 2002, records=[make_record("W2")])
    manifest = run(extract_root, bronze_root, [2001, 2002])

    assert (bronze_root / "2002.parquet").exists()
    assert manifest_row(manifest, 2002)["status"] == "ingested"
    # 2001 was not rewritten.
    assert (bronze_root / "2001.parquet").stat().st_mtime_ns == mtime_2001


def test_integrity_error_propagates_and_stops(extract_root, bronze_root):
    # R6
    make_extract_year(extract_root, 2002, records=[make_record(None)])
    with pytest.raises(IntegrityError):
        run(extract_root, bronze_root, [2002])


def test_corrupted_state_propagates(extract_root, bronze_root):
    # R7
    make_extract_year(extract_root, 2002, records=[make_record("W1")])
    corrupt_page_line(extract_root / "2002" / "page-0001.jsonl", line_no=0)
    with pytest.raises(CorruptedState):
        run(extract_root, bronze_root, [2002])


def test_returned_manifest_equals_written_manifest(extract_root, bronze_root):
    # R8
    make_extract_year(extract_root, 2001, records=[make_record("W1")])
    make_extract_year(extract_root, 2002, complete=False)

    returned = run(extract_root, bronze_root, [2001, 2002])
    on_disk = read_manifest(bronze_root)

    assert returned.sort("publication_year").equals(on_disk.sort("publication_year"))
