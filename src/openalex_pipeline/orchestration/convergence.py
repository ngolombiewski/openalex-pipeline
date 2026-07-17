"""Convergence and warehouse-staleness predicates.

These functions import no Dagster APIs and write no state. Cloud metadata is
passed in by callers so predicate behavior remains unit-testable.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from datetime import datetime
import json
from pathlib import Path
from typing import Literal, cast

from openalex_pipeline.extraction.models import YearState
from openalex_pipeline.extraction.runner import canonical_query
from openalex_pipeline.extraction.storage import classify_year
from openalex_pipeline.orchestration.exceptions import (
    UnsupportedDbtMaterialization,
    WarehouseMetadataInvalid,
)
from openalex_pipeline.orchestration.invalidate import pending_invalidation_years
from openalex_pipeline.orchestration.models import (
    DbtRelationSpec,
    WarehouseRelationMetadata,
)
from openalex_pipeline.upload.core import should_skip


def is_converged(
    extract_root: Path,
    bronze_root: Path,
    years: Iterable[int],
    filter_str: str,
    gcs_updated_by_year: Mapping[int, datetime | None],
) -> bool:
    """Return whether another local sweep would change nothing.

    A valid pending invalidation makes the pipeline non-converged. Malformed or
    out-of-bounds tombstones raise ``TombstoneCorruption``. Otherwise every
    expected year must have COMPLETE extraction state, local bronze parquet,
    and a GCS object at least as fresh as that parquet. Extraction corruption
    and query mismatches propagate untouched.
    """
    expected_years = list(years)
    if pending_invalidation_years(extract_root, expected_years):
        return False

    for year in expected_years:
        query = canonical_query(filter_str, year)
        status = classify_year(extract_root, year, query)
        if status.state is not YearState.COMPLETE:
            return False

        parquet = bronze_root / f"{year}.parquet"
        if not parquet.exists():
            return False

        if not should_skip(parquet.stat().st_mtime, gcs_updated_by_year.get(year)):
            return False

    return True


def warehouse_is_stale(
    uploaded_at_values: Iterable[datetime],
    relation_metadata_by_name: Mapping[str, WarehouseRelationMetadata],
    expected_relations: Iterable[DbtRelationSpec],
) -> bool:
    """Return whether prod dbt relations are incomplete or stale.

    Every expected table/view must exist. Only table timestamps participate in
    data freshness: ``max(uploaded_at) > min(modified for expected tables)``.
    A present table without a modification timestamp cannot establish
    freshness and raises ``WarehouseMetadataInvalid``. Upload timestamps are a
    validated, non-empty manifest projection supplied by the caller.
    """
    latest_upload = max(uploaded_at_values)
    table_modified: list[datetime] = []
    for relation in expected_relations:
        metadata = relation_metadata_by_name.get(relation.name)
        if metadata is None or not metadata.exists:
            return True
        if relation.materialization == "table":
            if metadata.modified is None:
                raise WarehouseMetadataInvalid(
                    f"BigQuery table {relation.name!r} exists without modified metadata"
                )
            table_modified.append(metadata.modified)

    if not table_modified:
        raise WarehouseMetadataInvalid(
            "dbt manifest contains no table-materialized models for freshness"
        )
    return latest_upload > min(table_modified)


def dbt_model_relations(manifest_path: Path) -> list[DbtRelationSpec]:
    """Return immutable table/view specs for every dbt model in the manifest.

    This pipeline supports physical ``table`` and ``view`` materializations
    only. Any other model materialization raises rather than being inferred.
    """
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    relations: list[DbtRelationSpec] = []
    for node in manifest.get("nodes", {}).values():
        if node.get("resource_type") != "model":
            continue
        materialization = node.get("config", {}).get("materialized")
        if materialization not in {"table", "view"}:
            name = node.get("alias") or node.get("name")
            raise UnsupportedDbtMaterialization(
                f"dbt model {name!r} uses unsupported materialization "
                f"{materialization!r}; expected 'table' or 'view'"
            )
        relations.append(
            DbtRelationSpec(
                name=node.get("alias") or node["name"],
                materialization=cast(Literal["table", "view"], materialization),
            )
        )
    return sorted(relations)
