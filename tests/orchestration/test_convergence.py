from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

import pytest

from openalex_pipeline.extraction.exceptions import QueryMismatch
from openalex_pipeline.extraction.runner import canonical_query
from openalex_pipeline.extraction.storage import (
    finalize_year,
    initialize_year,
    write_page,
)
from openalex_pipeline.orchestration.convergence import (
    dbt_model_relations,
    is_converged,
    warehouse_is_stale,
)
from openalex_pipeline.orchestration.exceptions import (
    TombstoneCorruption,
    UnsupportedDbtMaterialization,
    WarehouseMetadataInvalid,
)
from openalex_pipeline.orchestration.models import (
    DbtRelationSpec,
    WarehouseRelationMetadata,
)


def _complete_year(root: Path, year: int, query: str) -> None:
    initialize_year(root, year, query, meta_count=1)
    write_page(root, year, [{"id": f"W{year}"}], None, 1)
    finalize_year(root, year)


def _closed_local_year(tmp_path: Path, year: int = 2026):
    extract_root = tmp_path / "extract"
    bronze_root = tmp_path / "bronze"
    query_filter = "primary_topic.field.id:17"
    _complete_year(extract_root, year, canonical_query(query_filter, year))
    parquet = bronze_root / f"{year}.parquet"
    parquet.parent.mkdir()
    parquet.write_bytes(b"parquet")
    local_mtime = datetime.fromtimestamp(parquet.stat().st_mtime, tz=timezone.utc)
    return extract_root, bronze_root, query_filter, local_mtime


def test_is_converged_when_extraction_bronze_and_gcs_are_closed(
    tmp_path: Path,
) -> None:
    extract_root, bronze_root, query_filter, local_mtime = _closed_local_year(tmp_path)

    assert is_converged(
        extract_root,
        bronze_root,
        [2026],
        query_filter,
        {2026: local_mtime + timedelta(seconds=1)},
    )


def test_is_converged_false_for_incomplete_extraction(tmp_path: Path) -> None:
    extract_root = tmp_path / "extract"
    bronze_root = tmp_path / "bronze"
    year = 2026
    query_filter = "primary_topic.field.id:17"
    query = canonical_query(query_filter, year)
    initialize_year(extract_root, year, query, meta_count=1)
    write_page(extract_root, year, [{"id": "W1"}], "next", 1)

    assert not is_converged(
        extract_root,
        bronze_root,
        [year],
        query_filter,
        {year: datetime.now(timezone.utc)},
    )


def test_is_converged_propagates_query_mismatch(tmp_path: Path) -> None:
    extract_root = tmp_path / "extract"
    year = 2026
    _complete_year(
        extract_root,
        year,
        canonical_query("primary_topic.field.id:17", year),
    )

    with pytest.raises(QueryMismatch):
        is_converged(
            extract_root,
            tmp_path / "bronze",
            [year],
            "primary_topic.field.id:18",
            {year: datetime.now(timezone.utc)},
        )


def test_is_converged_false_for_missing_or_stale_gcs(tmp_path: Path) -> None:
    extract_root, bronze_root, query_filter, local_mtime = _closed_local_year(tmp_path)

    assert not is_converged(
        extract_root, bronze_root, [2026], query_filter, {2026: None}
    )
    assert not is_converged(
        extract_root,
        bronze_root,
        [2026],
        query_filter,
        {2026: local_mtime - timedelta(seconds=1)},
    )


def test_is_converged_false_while_invalidation_is_pending(tmp_path: Path) -> None:
    extract_root, bronze_root, query_filter, local_mtime = _closed_local_year(tmp_path)
    (extract_root / "_INVALIDATING_2026").touch()

    assert not is_converged(
        extract_root,
        bronze_root,
        [2026],
        query_filter,
        {2026: local_mtime + timedelta(seconds=1)},
    )


@pytest.mark.parametrize(
    "marker",
    ["_INVALIDATING_nope", "_INVALIDATING_02026", "_INVALIDATING_2025"],
)
def test_is_converged_rejects_invalid_tombstones(tmp_path: Path, marker: str) -> None:
    extract_root = tmp_path / "extract"
    extract_root.mkdir()
    (extract_root / marker).touch()

    with pytest.raises(TombstoneCorruption):
        is_converged(extract_root, tmp_path / "bronze", [2026], "filter", {})


TABLE = DbtRelationSpec("stg_works", "table")
VIEW = DbtRelationSpec("int_paper_half_life", "view")


def test_warehouse_stale_uses_table_timestamps_only() -> None:
    uploaded = datetime(2026, 7, 9, 12, tzinfo=timezone.utc)

    assert warehouse_is_stale(
        [uploaded],
        {
            TABLE.name: WarehouseRelationMetadata(
                True, uploaded - timedelta(minutes=1)
            ),
            VIEW.name: WarehouseRelationMetadata(True, None),
        },
        [TABLE, VIEW],
    )
    assert not warehouse_is_stale(
        [uploaded],
        {
            TABLE.name: WarehouseRelationMetadata(
                True, uploaded + timedelta(minutes=1)
            ),
            VIEW.name: WarehouseRelationMetadata(True, uploaded - timedelta(days=100)),
        },
        [TABLE, VIEW],
    )


@pytest.mark.parametrize("missing", [TABLE, VIEW])
def test_warehouse_stale_when_any_relation_is_missing(
    missing: DbtRelationSpec,
) -> None:
    uploaded = datetime(2026, 7, 9, 12, tzinfo=timezone.utc)
    metadata = {
        TABLE.name: WarehouseRelationMetadata(True, uploaded + timedelta(minutes=1)),
        VIEW.name: WarehouseRelationMetadata(True, None),
    }
    metadata[missing.name] = WarehouseRelationMetadata(False, None)

    assert warehouse_is_stale([uploaded], metadata, [TABLE, VIEW])


def test_warehouse_rejects_present_table_without_modified_timestamp() -> None:
    uploaded = datetime(2026, 7, 9, 12, tzinfo=timezone.utc)

    with pytest.raises(WarehouseMetadataInvalid):
        warehouse_is_stale(
            [uploaded],
            {TABLE.name: WarehouseRelationMetadata(True, None)},
            [TABLE],
        )


def test_dbt_model_relations_surface_tables_and_views(tmp_path: Path) -> None:
    manifest = {
        "nodes": {
            "model.openalex.stg_works": {
                "resource_type": "model",
                "name": "stg_works",
                "config": {"materialized": "table"},
            },
            "model.openalex.renamed": {
                "resource_type": "model",
                "name": "logical_name",
                "alias": "physical_name",
                "config": {"materialized": "view"},
            },
            "test.openalex.not_null": {"resource_type": "test", "name": "not_null"},
        }
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    assert dbt_model_relations(path) == [
        DbtRelationSpec("physical_name", "view"),
        DbtRelationSpec("stg_works", "table"),
    ]


def test_dbt_model_relations_reject_unsupported_materialization(tmp_path: Path) -> None:
    manifest = {
        "nodes": {
            "model.openalex.incremental": {
                "resource_type": "model",
                "name": "incremental",
                "config": {"materialized": "incremental"},
            }
        }
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(UnsupportedDbtMaterialization):
        dbt_model_relations(path)
