"""Tests for bronze.core: classify_year, ingest_year, write_empty_year.

Covers the C-series in docs/bronze-tests.md.
"""

from __future__ import annotations

import json

import polars as pl
import pytest

from openalex_pipeline.bronze.core import (
    YearState,
    classify_year,
    ingest_year,
    write_empty_year,
)
from openalex_pipeline.bronze.errors import CorruptedState, IntegrityError
from openalex_pipeline.bronze.schema import BRONZE_SCHEMA

from .conftest import (
    corrupt_page_line,
    make_extract_year,
    make_record,
    read_year_parquet,
    tmp_files,
)


# --- classify_year ----------------------------------------------------------

def test_parquet_present_classifies_ingested(extract_root, bronze_root):
    # C1: existence of the output Parquet is the only signal; no extraction dir.
    (bronze_root / "2002.parquet").write_bytes(b"not even a real parquet")
    assert classify_year(extract_root, bronze_root, 2002) is YearState.INGESTED


def test_ready_when_report_and_pages_present(extract_root, bronze_root):
    # C2
    make_extract_year(extract_root, 2002, complete=True)
    assert classify_year(extract_root, bronze_root, 2002) is YearState.READY


def test_pending_when_dir_present_without_report(extract_root, bronze_root):
    # C3: directory present but extraction not complete.
    make_extract_year(extract_root, 2002, complete=False)
    assert classify_year(extract_root, bronze_root, 2002) is YearState.PENDING


def test_pending_when_no_extraction_dir(extract_root, bronze_root):
    # C4
    assert classify_year(extract_root, bronze_root, 2002) is YearState.PENDING


def test_report_present_but_zero_pages_is_corrupt(extract_root, bronze_root):
    # C5
    make_extract_year(extract_root, 2002, complete=True, no_pages=True)
    with pytest.raises(CorruptedState):
        classify_year(extract_root, bronze_root, 2002)


def test_parquet_present_wins_over_corrupt_extraction(extract_root, bronze_root):
    # C6: the parquet check precedes the corruption check.
    make_extract_year(extract_root, 2002, complete=True, no_pages=True)
    (bronze_root / "2002.parquet").write_bytes(b"placeholder")
    assert classify_year(extract_root, bronze_root, 2002) is YearState.INGESTED


# --- ingest_year: READY happy path ------------------------------------------

def test_ingest_ready_writes_parquet_and_result(extract_root, bronze_root):
    # C7
    records = [make_record("W1"), make_record("W2"), make_record("W3")]
    make_extract_year(extract_root, 2002, records=records)

    result = ingest_year(extract_root, bronze_root, 2002)

    assert result.state is YearState.READY
    assert result.bronze_row_count == 3
    assert result.duplicate_id_count == 0
    # G3: YearIngestResult carries the ABSOLUTE path.
    assert result.bronze_file_path == (bronze_root / "2002.parquet")
    assert result.bronze_file_path.is_absolute()
    assert (bronze_root / "2002.parquet").exists()
    assert tmp_files(bronze_root) == []


def test_written_parquet_has_exact_ordered_schema(extract_root, bronze_root):
    # C8: exact dtypes and canonical column order (Q2).
    make_extract_year(extract_root, 2002, records=[make_record("W1")])
    ingest_year(extract_root, bronze_root, 2002)

    frame = read_year_parquet(bronze_root, 2002)
    assert list(frame.columns) == list(BRONZE_SCHEMA.keys())
    assert frame.schema == pl.Schema(BRONZE_SCHEMA)


def test_nested_fields_landed_as_verbatim_json_without_fabricated_keys(extract_root, bronze_root):
    # C9: forced-String fidelity. One record's `ids` has a pmid key, the other
    # omits it; the omitting record must NOT gain a fabricated "pmid": null.
    with_pmid = make_record(
        "W1", ids={"openalex": "https://openalex.org/W1", "pmid": "https://pubmed/1"}
    )
    without_pmid = make_record("W2", ids={"openalex": "https://openalex.org/W2"})
    make_extract_year(extract_root, 2002, records=[with_pmid, without_pmid])

    ingest_year(extract_root, bronze_root, 2002)
    frame = read_year_parquet(bronze_root, 2002).sort("id")

    ids_col = frame["ids"].to_list()
    # Nested column is String.
    assert frame.schema["ids"] == pl.String
    parsed_w1 = json.loads(ids_col[0])
    parsed_w2 = json.loads(ids_col[1])
    # Verbatim: equals the raw source object exactly.
    assert parsed_w1 == with_pmid["ids"]
    assert parsed_w2 == without_pmid["ids"]
    # No key fabrication: the pmid-less record has no pmid key at all.
    assert "pmid" not in parsed_w2


def test_multi_page_year_read_in_one_pass(extract_root, bronze_root):
    # C10
    pages = [
        [make_record("W1"), make_record("W2")],
        [make_record("W3")],
        [make_record("W4"), make_record("W5")],
    ]
    make_extract_year(extract_root, 2002, pages=pages)

    result = ingest_year(extract_root, bronze_root, 2002)
    assert result.bronze_row_count == 5

    ids = set(read_year_parquet(bronze_root, 2002)["id"].to_list())
    assert ids == {"W1", "W2", "W3", "W4", "W5"}


# --- ingest_year: duplicate ids (non-blocking) ------------------------------

def test_duplicate_id_count_is_excess_rows(extract_root, bronze_root):
    # C11: one id appears 3x (-> 2 excess), another 2x (-> 1 excess) => 3.
    records = [
        make_record("W1"),
        make_record("W1"),
        make_record("W1"),
        make_record("W2"),
        make_record("W2"),
        make_record("W3"),
    ]
    make_extract_year(extract_root, 2002, records=records)

    result = ingest_year(extract_root, bronze_root, 2002)

    # Non-blocking: still written, no raise.
    assert (bronze_root / "2002.parquet").exists()
    assert result.bronze_row_count == 6
    assert result.duplicate_id_count == 3


# --- ingest_year: loud failures ---------------------------------------------

def test_null_id_raises_integrity_error_and_writes_nothing(extract_root, bronze_root):
    # C12: assertion precedes write -> no parquet, no tmp.
    make_extract_year(extract_root, 2002, records=[make_record("W1"), make_record(None)])

    with pytest.raises(IntegrityError):
        ingest_year(extract_root, bronze_root, 2002)

    assert not (bronze_root / "2002.parquet").exists()
    assert tmp_files(bronze_root) == []


def test_scalar_type_mismatch_raises_corrupted_state(extract_root, bronze_root):
    # C13 (G1): a wrong-typed scalar -> Polars ComputeError, wrapped as CorruptedState.
    make_extract_year(
        extract_root, 2002, records=[make_record("W1", cited_by_count="lots")]
    )

    with pytest.raises(CorruptedState):
        ingest_year(extract_root, bronze_root, 2002)

    assert not (bronze_root / "2002.parquet").exists()
    assert tmp_files(bronze_root) == []


def test_row_count_mismatch_raises_integrity_error(extract_root, bronze_root):
    # C20: parquet row count != _YEAR_REPORT.records_fetched -> loud, no write.
    # Two real records on disk, but the report claims 99.
    make_extract_year(
        extract_root,
        2002,
        records=[make_record("W1"), make_record("W2")],
        report={"records_fetched": 99, "expected_count": 99},
    )

    with pytest.raises(IntegrityError):
        ingest_year(extract_root, bronze_root, 2002)

    assert not (bronze_root / "2002.parquet").exists()
    assert tmp_files(bronze_root) == []


def test_malformed_jsonl_raises_corrupted_state(extract_root, bronze_root):
    # C14
    make_extract_year(extract_root, 2002, records=[make_record("W1"), make_record("W2")])
    corrupt_page_line(extract_root / "2002" / "page-0001.jsonl", line_no=0)

    with pytest.raises(CorruptedState):
        ingest_year(extract_root, bronze_root, 2002)

    assert not (bronze_root / "2002.parquet").exists()
    assert tmp_files(bronze_root) == []


# --- ingest_year: INGESTED / PENDING short-circuits -------------------------

def test_ingest_already_ingested_year_does_not_rewrite(extract_root, bronze_root):
    # C15: INGESTED -> no read, no write; existing parquet untouched.
    make_extract_year(extract_root, 2002, records=[make_record("W1")])
    ingest_year(extract_root, bronze_root, 2002)
    parquet = bronze_root / "2002.parquet"
    mtime_before = parquet.stat().st_mtime_ns

    result = ingest_year(extract_root, bronze_root, 2002)

    assert result.state is YearState.INGESTED
    assert result.bronze_file_path == parquet
    assert result.bronze_row_count is None
    assert result.duplicate_id_count is None
    assert parquet.stat().st_mtime_ns == mtime_before


def test_ingest_pending_year_writes_nothing(extract_root, bronze_root):
    # C16
    make_extract_year(extract_root, 2002, complete=False)

    result = ingest_year(extract_root, bronze_root, 2002)

    assert result.state is YearState.PENDING
    assert result.bronze_row_count is None
    assert result.duplicate_id_count is None
    assert result.bronze_file_path is None
    assert not (bronze_root / "2002.parquet").exists()


# --- empty-year path --------------------------------------------------------

def test_zero_result_year_via_ingest_writes_empty_parquet(extract_root, bronze_root):
    # C17
    make_extract_year(extract_root, 2002, empty=True)

    result = ingest_year(extract_root, bronze_root, 2002)

    frame = read_year_parquet(bronze_root, 2002)
    assert frame.height == 0
    assert frame.schema == pl.Schema(BRONZE_SCHEMA)
    assert result.bronze_row_count == 0
    assert result.duplicate_id_count == 0


def test_write_empty_year_directly(extract_root, bronze_root):
    # C18
    path = write_empty_year(bronze_root, 2002)

    assert path == (bronze_root / "2002.parquet")
    frame = pl.read_parquet(path)
    assert frame.height == 0
    assert list(frame.columns) == list(BRONZE_SCHEMA.keys())
    assert frame.schema == pl.Schema(BRONZE_SCHEMA)
    assert tmp_files(bronze_root) == []


@pytest.mark.parametrize(
    "kwargs",
    [
        {"zero_byte_extra": True},               # zero-byte page alongside non-empty page
        {"empty": True, "extra_zero_byte_pages": 1},  # two zero-byte pages
    ],
)
def test_disallowed_zero_byte_combos_raise_corrupted_state(extract_root, bronze_root, kwargs):
    # C19 (G4)
    make_extract_year(extract_root, 2002, **kwargs)

    with pytest.raises(CorruptedState):
        ingest_year(extract_root, bronze_root, 2002)

    assert not (bronze_root / "2002.parquet").exists()
    assert tmp_files(bronze_root) == []
