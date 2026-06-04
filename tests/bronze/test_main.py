"""Tests for bronze.__main__: parse_args, resolve_roots, build_years_list, main.

Covers the A-series in docs/bronze-tests.md.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from openalex_pipeline.bronze.__main__ import (
    build_years_list,
    main,
    parse_args,
    resolve_roots,
)
from openalex_pipeline.bronze.errors import CorruptedState

from .conftest import make_extract_year, make_record, read_manifest

ENV = "OPENALEX_DATA_ROOT"


# --- parse_args -------------------------------------------------------------

def test_parse_args_reads_flags(tmp_path):
    # A1
    args = parse_args(
        [
            "--extract-root", str(tmp_path / "e"),
            "--bronze-root", str(tmp_path / "b"),
            "--years", "1950:1960",
        ]
    )
    assert args.extract_root == Path(tmp_path / "e")
    assert args.bronze_root == Path(tmp_path / "b")
    assert args.years == "1950:1960"


def test_parse_args_years_defaults_to_none(tmp_path):
    args = parse_args(["--extract-root", str(tmp_path), "--bronze-root", str(tmp_path)])
    assert args.years is None


# --- resolve_roots ----------------------------------------------------------

def test_resolve_roots_flags_win_over_env(tmp_path, monkeypatch):
    # A2
    monkeypatch.setenv(ENV, str(tmp_path / "env_root"))
    extract = tmp_path / "flag_extract"
    extract.mkdir()
    bronze = tmp_path / "flag_bronze"
    args = parse_args(["--extract-root", str(extract), "--bronze-root", str(bronze)])

    assert resolve_roots(args) == (extract, bronze)


def test_resolve_roots_falls_back_to_env(tmp_path, monkeypatch):
    # A3
    root = tmp_path / "data"
    (root / "extract").mkdir(parents=True)
    monkeypatch.setenv(ENV, str(root))
    args = parse_args([])

    assert resolve_roots(args) == (root / "extract", root / "bronze")


def test_resolve_roots_missing_config_exits(monkeypatch):
    # A4
    monkeypatch.delenv(ENV, raising=False)
    args = parse_args([])
    with pytest.raises(SystemExit):
        resolve_roots(args)


def test_resolve_roots_absent_extract_root_exits(tmp_path, monkeypatch):
    # A5
    monkeypatch.delenv(ENV, raising=False)
    args = parse_args(["--extract-root", str(tmp_path / "missing"), "--bronze-root", str(tmp_path)])
    with pytest.raises(SystemExit):
        resolve_roots(args)


# --- build_years_list -------------------------------------------------------

def test_build_years_list_explicit_range_inclusive(extract_root):
    # A6
    assert build_years_list(extract_root, "1953:1955") == [1953, 1954, 1955]


def test_explicit_range_includes_years_with_no_dir(extract_root):
    # A7: the range is the universe; absent years stay in (classify PENDING later).
    make_extract_year(extract_root, 1954, complete=False)
    assert build_years_list(extract_root, "1953:1955") == [1953, 1954, 1955]


def test_build_years_list_discover_mode(extract_root):
    # A8: every numeric subdir, sorted; non-numeric dirs and files ignored.
    make_extract_year(extract_root, 2002, records=[make_record("W1")])
    make_extract_year(extract_root, 2000, records=[make_record("W2")])
    (extract_root / "not_a_year").mkdir()
    (extract_root / "_MANIFEST.parquet").write_bytes(b"")

    assert build_years_list(extract_root, None) == [2000, 2002]


def test_discover_mode_excludes_missing_dirs_includes_incomplete(extract_root):
    # A9: present-incomplete dir appears (-> PENDING); missing-dir year absent.
    make_extract_year(extract_root, 2000, records=[make_record("W1")])  # complete
    make_extract_year(extract_root, 2001, complete=False)               # incomplete
    # 2002 has no dir at all.

    assert build_years_list(extract_root, None) == [2000, 2001]


@pytest.mark.parametrize("years_arg", ["abc", "1950:", ":1960", "1950:1940", "1950-1960"])
def test_build_years_list_malformed_range_exits(extract_root, years_arg):
    # A10a
    with pytest.raises(SystemExit):
        build_years_list(extract_root, years_arg)


def test_build_years_list_discover_empty_exits(extract_root):
    # A10b: discover mode with no numeric subdirs.
    with pytest.raises(SystemExit):
        build_years_list(extract_root, None)


# --- main (end to end) ------------------------------------------------------

def test_main_explicit_range_end_to_end(extract_root, bronze_root):
    # A11
    make_extract_year(extract_root, 1953, records=[make_record("W1")])
    make_extract_year(extract_root, 1954, records=[make_record("W2")])

    main(
        [
            "--extract-root", str(extract_root),
            "--bronze-root", str(bronze_root),
            "--years", "1953:1954",
        ]
    )

    assert (bronze_root / "1953.parquet").exists()
    assert (bronze_root / "1954.parquet").exists()
    manifest = read_manifest(bronze_root)
    assert sorted(manifest["publication_year"].to_list()) == [1953, 1954]


def test_main_discover_mode_end_to_end(extract_root, bronze_root):
    # A12
    make_extract_year(extract_root, 2000, records=[make_record("W1")])

    main(["--extract-root", str(extract_root), "--bronze-root", str(bronze_root)])

    assert (bronze_root / "2000.parquet").exists()


def test_main_surfaces_warnings(extract_root, bronze_root, loguru_messages):
    # A13: non-zero duplicate_id_count and count_mismatch surface as warnings,
    # via loguru, and the run still succeeds.
    make_extract_year(
        extract_root, 2001, records=[make_record("W1"), make_record("W1")]
    )  # duplicate id
    make_extract_year(
        extract_root, 2002, records=[make_record("W2")], report={"count_mismatch": True}
    )

    main(
        [
            "--extract-root", str(extract_root),
            "--bronze-root", str(bronze_root),
            "--years", "2001:2002",
        ]
    )

    blob = "\n".join(loguru_messages).lower()
    assert "duplicate" in blob
    assert "mismatch" in blob
    # The run succeeded despite the warnings.
    assert (bronze_root / "2001.parquet").exists()
    assert (bronze_root / "2002.parquet").exists()


def test_main_does_not_swallow_bronze_error(extract_root, bronze_root):
    # A14
    make_extract_year(extract_root, 2002, records=[make_record("W1", cited_by_count="lots")])

    with pytest.raises(CorruptedState):
        main(
            [
                "--extract-root", str(extract_root),
                "--bronze-root", str(bronze_root),
                "--years", "2002:2002",
            ]
        )
