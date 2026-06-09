"""Tests for the upload module: skip logic, per-year upload, manifest, CLI.

The GCS boundary is faked (see conftest); the local filesystem is real.
"""

from __future__ import annotations

import io
from datetime import timedelta

import polars as pl
import pytest

from openalex_pipeline.upload import core, manifest, runner
from openalex_pipeline.upload.__main__ import (
    parse_args,
    resolve_bronze_root,
    resolve_bucket_name,
)

from .conftest import (
    BASE_MTIME,
    BASE_MTIME_UTC,
    UPLOAD_TIME,
    make_bronze_parquet,
)


# --- Path helpers -----------------------------------------------------------

def test_gcs_object_name_is_hive_partitioned():
    assert core.gcs_object_name(1950) == "bronze/publication_year=1950/1950.parquet"


def test_gcs_uri_is_full():
    assert core.gcs_uri("openalex-pipeline-bronze", 1950) == (
        "gs://openalex-pipeline-bronze/bronze/publication_year=1950/1950.parquet"
    )


# --- discover_years ---------------------------------------------------------

def test_discover_years_returns_digit_stems_sorted(bronze_root):
    make_bronze_parquet(bronze_root, 1952)
    make_bronze_parquet(bronze_root, 1950)
    make_bronze_parquet(bronze_root, 1951)
    assert core.discover_years(bronze_root) == [1950, 1951, 1952]


def test_discover_years_excludes_manifest_and_tmp(bronze_root):
    make_bronze_parquet(bronze_root, 1950)
    (bronze_root / "_MANIFEST.parquet").write_bytes(b"x")
    (bronze_root / "1951.parquet.tmp").write_bytes(b"x")
    assert core.discover_years(bronze_root) == [1950]


def test_discover_years_empty_when_no_parquet(bronze_root):
    assert core.discover_years(bronze_root) == []


# --- should_skip (the three-case table from the design) ---------------------

def test_should_skip_object_newer_skips():
    # Object updated 1s after local mtime -> skip.
    assert core.should_skip(BASE_MTIME, BASE_MTIME_UTC + timedelta(seconds=1)) is True


def test_should_skip_local_newer_uploads():
    # Object updated 1s before local mtime -> (re-)upload.
    assert core.should_skip(BASE_MTIME, BASE_MTIME_UTC - timedelta(seconds=1)) is False


def test_should_skip_object_absent_uploads():
    assert core.should_skip(BASE_MTIME, None) is False


def test_should_skip_equal_timestamps_skips():
    # >= : an object exactly as old as the local file is fresh enough.
    assert core.should_skip(BASE_MTIME, BASE_MTIME_UTC) is True


# --- upload_year ------------------------------------------------------------

def test_upload_year_uploads_when_absent(bronze_root, bucket):
    make_bronze_parquet(bronze_root, 1950)
    result = core.upload_year(bucket, bronze_root, 1950)

    assert result.uploaded is True
    assert result.year == 1950
    assert result.gcs_path == core.gcs_uri(bucket.name, 1950)
    assert result.uploaded_at == UPLOAD_TIME
    assert result.file_size_bytes > 0
    # The blob actually received the local file.
    blob = bucket.blob(core.gcs_object_name(1950))
    assert blob.uploaded_from == str(bronze_root / "1950.parquet")


def test_upload_year_skips_when_object_newer(bronze_root, bucket):
    make_bronze_parquet(bronze_root, 1950, mtime=BASE_MTIME)
    bucket.preset(
        core.gcs_object_name(1950),
        size=999,
        updated=BASE_MTIME_UTC + timedelta(seconds=1),
    )
    result = core.upload_year(bucket, bronze_root, 1950)

    assert result.uploaded is False
    # Metadata is the existing blob's, not a fresh upload's.
    assert result.file_size_bytes == 999
    assert result.uploaded_at == BASE_MTIME_UTC + timedelta(seconds=1)
    assert bucket.blob(core.gcs_object_name(1950)).uploaded_from is None


def test_upload_year_reuploads_when_local_newer(bronze_root, bucket):
    make_bronze_parquet(bronze_root, 1950, mtime=BASE_MTIME)
    bucket.preset(
        core.gcs_object_name(1950),
        size=999,
        updated=BASE_MTIME_UTC - timedelta(seconds=1),
    )
    result = core.upload_year(bucket, bronze_root, 1950)

    assert result.uploaded is True
    # Metadata reflects the fresh upload, not the stale preset.
    assert result.uploaded_at == UPLOAD_TIME
    assert result.file_size_bytes != 999


# --- manifest ---------------------------------------------------------------

def test_build_manifest_schema_and_rows(bronze_root, bucket):
    make_bronze_parquet(bronze_root, 1950)
    make_bronze_parquet(bronze_root, 1951)
    results = [
        core.upload_year(bucket, bronze_root, 1950),
        core.upload_year(bucket, bronze_root, 1951),
    ]
    df = manifest.build_manifest(results)

    assert df.schema == pl.Schema(manifest.UPLOAD_MANIFEST_SCHEMA)
    assert df["publication_year"].to_list() == [1950, 1951]
    assert df["gcs_path"].to_list() == [
        core.gcs_uri(bucket.name, 1950),
        core.gcs_uri(bucket.name, 1951),
    ]
    assert df["uploaded_at"].to_list() == [UPLOAD_TIME, UPLOAD_TIME]


def test_write_manifest_uploads_readable_parquet(bucket):
    df = manifest.build_manifest([])
    uri = manifest.write_manifest(bucket, df)

    assert uri == f"gs://{bucket.name}/{manifest.MANIFEST_OBJECT_NAME}"
    blob = bucket.blob(manifest.MANIFEST_OBJECT_NAME)
    assert blob.uploaded_bytes is not None
    # The uploaded bytes round-trip as a Parquet with the manifest schema.
    roundtrip = pl.read_parquet(io.BytesIO(blob.uploaded_bytes))
    assert roundtrip.schema == pl.Schema(manifest.UPLOAD_MANIFEST_SCHEMA)


def test_manifest_object_name_outside_bronze_prefix():
    # Must not live under bronze/publication_year=*/ (BigQuery's glob).
    assert not manifest.MANIFEST_OBJECT_NAME.startswith("bronze/")
    assert manifest.MANIFEST_OBJECT_NAME == "upload/_MANIFEST.parquet"


# --- runner -----------------------------------------------------------------

def test_run_uploads_all_years_and_writes_manifest(bronze_root, bucket):
    make_bronze_parquet(bronze_root, 1950)
    make_bronze_parquet(bronze_root, 1951)

    results = runner.run(bronze_root, bucket)

    assert [r.year for r in results] == [1950, 1951]
    assert all(r.uploaded for r in results)
    # Manifest written, last, and readable.
    blob = bucket.blob(manifest.MANIFEST_OBJECT_NAME)
    roundtrip = pl.read_parquet(io.BytesIO(blob.uploaded_bytes))
    assert roundtrip["publication_year"].to_list() == [1950, 1951]


def test_run_skips_up_to_date_years(bronze_root, bucket):
    make_bronze_parquet(bronze_root, 1950, mtime=BASE_MTIME)
    bucket.preset(
        core.gcs_object_name(1950),
        size=999,
        updated=BASE_MTIME_UTC + timedelta(seconds=1),
    )
    make_bronze_parquet(bronze_root, 1951, mtime=BASE_MTIME)

    results = runner.run(bronze_root, bucket)

    by_year = {r.year: r for r in results}
    assert by_year[1950].uploaded is False
    assert by_year[1951].uploaded is True


def test_run_empty_bronze_writes_empty_manifest(bronze_root, bucket):
    results = runner.run(bronze_root, bucket)

    assert results == []
    blob = bucket.blob(manifest.MANIFEST_OBJECT_NAME)
    roundtrip = pl.read_parquet(io.BytesIO(blob.uploaded_bytes))
    assert roundtrip.height == 0
    assert roundtrip.schema == pl.Schema(manifest.UPLOAD_MANIFEST_SCHEMA)


# --- CLI: resolve_bronze_root -----------------------------------------------

def test_resolve_bronze_root_flag_wins(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENALEX_DATA_ROOT", str(tmp_path / "env"))
    flag = tmp_path / "flag"
    flag.mkdir()
    args = parse_args(["--bronze-root", str(flag)])
    assert resolve_bronze_root(args) == flag


def test_resolve_bronze_root_falls_back_to_env(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENALEX_DATA_ROOT", str(tmp_path))
    (tmp_path / "bronze").mkdir()
    args = parse_args([])
    assert resolve_bronze_root(args) == tmp_path / "bronze"


def test_resolve_bronze_root_unset_raises(monkeypatch):
    monkeypatch.delenv("OPENALEX_DATA_ROOT", raising=False)
    args = parse_args([])
    with pytest.raises(SystemExit):
        resolve_bronze_root(args)


def test_resolve_bronze_root_nonexistent_raises(tmp_path):
    args = parse_args(["--bronze-root", str(tmp_path / "nope")])
    with pytest.raises(SystemExit):
        resolve_bronze_root(args)


# --- CLI: resolve_bucket_name -----------------------------------------------

def test_resolve_bucket_name_flag_wins(monkeypatch):
    monkeypatch.setenv("OPENALEX_GCS_BUCKET", "env-bucket")
    args = parse_args(["--bucket", "flag-bucket"])
    assert resolve_bucket_name(args) == "flag-bucket"


def test_resolve_bucket_name_falls_back_to_env(monkeypatch):
    monkeypatch.setenv("OPENALEX_GCS_BUCKET", "env-bucket")
    args = parse_args([])
    assert resolve_bucket_name(args) == "env-bucket"


def test_resolve_bucket_name_unset_raises(monkeypatch):
    monkeypatch.delenv("OPENALEX_GCS_BUCKET", raising=False)
    args = parse_args([])
    with pytest.raises(SystemExit):
        resolve_bucket_name(args)
