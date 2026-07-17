from pathlib import Path

import pytest

from openalex_pipeline.bronze.core import assert_query_homogeneity
from openalex_pipeline.extraction.exceptions import CorruptedState, QueryMismatch
from openalex_pipeline.extraction.runner import canonical_query
from openalex_pipeline.extraction.storage import (
    finalize_year,
    initialize_year,
    write_page,
)
from openalex_pipeline.orchestration.exceptions import TombstoneCorruption
from openalex_pipeline.orchestration.invalidate import (
    InvalidationRequestStatus,
    request_year_invalidation,
    resume_pending_invalidations,
)
from openalex_pipeline.upload.core import discover_years


def _complete_year(root: Path, year: int, query: str) -> None:
    initialize_year(root, year, query, meta_count=1)
    write_page(root, year, [{"id": "W1"}], None, 1)
    finalize_year(root, year)


def _in_progress_year(root: Path, year: int, query: str) -> None:
    initialize_year(root, year, query, meta_count=2)
    write_page(root, year, [{"id": "W1"}], "next", 1)


def test_request_writes_durable_tombstone_without_deleting(tmp_path: Path) -> None:
    extract_root = tmp_path / "extract"
    bronze_root = tmp_path / "bronze"
    year = 2026
    query = canonical_query("primary_topic.field.id:17", year)
    _complete_year(extract_root, year, query)
    parquet = bronze_root / f"{year}.parquet"
    parquet.parent.mkdir()
    parquet.write_bytes(b"parquet")

    result = request_year_invalidation(extract_root, year, query)

    assert result.status is InvalidationRequestStatus.REQUESTED
    assert (extract_root / f"_INVALIDATING_{year}").read_bytes() == b""
    assert (extract_root / str(year)).exists()
    assert parquet.exists()


def test_existing_tombstone_wins_over_absent_year(tmp_path: Path) -> None:
    extract_root = tmp_path / "extract"
    extract_root.mkdir()
    (extract_root / "_INVALIDATING_2026").touch()

    result = request_year_invalidation(extract_root, 2026, "query")

    assert result.status is InvalidationRequestStatus.SKIPPED_PENDING


def test_request_in_progress_and_absent_are_noops(tmp_path: Path) -> None:
    extract_root = tmp_path / "extract"
    year = 2026
    query = canonical_query("primary_topic.field.id:17", year)
    _in_progress_year(extract_root, year, query)

    in_progress = request_year_invalidation(extract_root, year, query)
    absent = request_year_invalidation(tmp_path / "absent", year, query)

    assert in_progress.status is InvalidationRequestStatus.SKIPPED_IN_PROGRESS
    assert absent.status is InvalidationRequestStatus.SKIPPED_ABSENT
    assert not (extract_root / f"_INVALIDATING_{year}").exists()


def test_request_propagates_corruption_and_query_mismatch(tmp_path: Path) -> None:
    extract_root = tmp_path / "extract"
    year = 2026
    year_dir = extract_root / str(year)
    year_dir.mkdir(parents=True)
    (year_dir / "_META.json").write_text("{}", encoding="utf-8")

    with pytest.raises(CorruptedState):
        request_year_invalidation(extract_root, year, "query")

    other_root = tmp_path / "other"
    _complete_year(
        other_root,
        year,
        canonical_query("primary_topic.field.id:17", year),
    )
    with pytest.raises(QueryMismatch):
        request_year_invalidation(
            other_root,
            year,
            canonical_query("primary_topic.field.id:18", year),
        )


@pytest.mark.parametrize(
    ("with_parquet", "with_year_dir", "deleted_bronze", "deleted_extraction"),
    [
        (True, True, True, True),
        (False, True, False, True),
        (False, False, False, False),
    ],
)
def test_executor_recovers_from_each_interruption_point(
    tmp_path: Path,
    with_parquet: bool,
    with_year_dir: bool,
    deleted_bronze: bool,
    deleted_extraction: bool,
) -> None:
    extract_root = tmp_path / "extract"
    bronze_root = tmp_path / "bronze"
    extract_root.mkdir()
    (extract_root / "_INVALIDATING_2026").touch()
    if with_year_dir:
        (extract_root / "2026").mkdir()
    if with_parquet:
        bronze_root.mkdir()
        (bronze_root / "2026.parquet").write_bytes(b"parquet")

    results = resume_pending_invalidations(extract_root, bronze_root, [2026])

    assert len(results) == 1
    assert results[0].year == 2026
    assert results[0].deleted_bronze is deleted_bronze
    assert results[0].deleted_extraction is deleted_extraction
    assert not (extract_root / "_INVALIDATING_2026").exists()


def test_request_then_execute_leaves_no_tombstone_or_local_artifacts(
    tmp_path: Path,
) -> None:
    extract_root = tmp_path / "extract"
    bronze_root = tmp_path / "bronze"
    year = 2026
    query = canonical_query("primary_topic.field.id:17", year)
    _complete_year(extract_root, year, query)
    bronze_root.mkdir()
    (bronze_root / f"{year}.parquet").write_bytes(b"parquet")

    request_year_invalidation(extract_root, year, query)
    results = resume_pending_invalidations(extract_root, bronze_root, [year])

    assert len(results) == 1
    assert not (extract_root / str(year)).exists()
    assert not (bronze_root / f"{year}.parquet").exists()
    assert not (extract_root / f"_INVALIDATING_{year}").exists()


def test_executor_without_tombstones_is_noop(tmp_path: Path) -> None:
    assert (
        resume_pending_invalidations(tmp_path / "extract", tmp_path / "bronze", [2026])
        == []
    )


@pytest.mark.parametrize(
    "marker",
    ["_INVALIDATING_nope", "_INVALIDATING_02026", "_INVALIDATING_2025"],
)
def test_executor_rejects_malformed_or_out_of_bounds_tombstone(
    tmp_path: Path, marker: str
) -> None:
    extract_root = tmp_path / "extract"
    extract_root.mkdir()
    (extract_root / marker).touch()

    with pytest.raises(TombstoneCorruption):
        resume_pending_invalidations(extract_root, tmp_path / "bronze", [2026])


def test_executor_rejects_symlink_tombstone_before_deleting(tmp_path: Path) -> None:
    extract_root = tmp_path / "extract"
    bronze_root = tmp_path / "bronze"
    year_dir = extract_root / "2026"
    parquet = bronze_root / "2026.parquet"
    year_dir.mkdir(parents=True)
    parquet.parent.mkdir()
    parquet.write_bytes(b"parquet")
    target = tmp_path / "marker-target"
    target.touch()
    (extract_root / "_INVALIDATING_2026").symlink_to(target)

    with pytest.raises(TombstoneCorruption, match="regular marker file"):
        resume_pending_invalidations(extract_root, bronze_root, [2026])

    assert year_dir.exists()
    assert parquet.exists()


def test_layer_discovery_ignores_tombstones(tmp_path: Path) -> None:
    extract_root = tmp_path / "extract"
    bronze_root = tmp_path / "bronze"
    extract_root.mkdir()
    bronze_root.mkdir()
    (extract_root / "_INVALIDATING_2026").touch()
    (bronze_root / "_INVALIDATING_2026.parquet").touch()
    (bronze_root / "2026.parquet").touch()

    assert_query_homogeneity(extract_root, [2026])
    assert discover_years(bronze_root) == [2026]
