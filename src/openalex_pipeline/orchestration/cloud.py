"""Cloud metadata helpers for orchestration predicates."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime
from io import BytesIO

from google.api_core.exceptions import NotFound
from google.cloud import bigquery, storage
import polars as pl

from openalex_pipeline.orchestration.exceptions import UploadManifestInvalid
from openalex_pipeline.orchestration.models import (
    DbtRelationSpec,
    WarehouseRelationMetadata,
)
from openalex_pipeline.upload.core import gcs_object_name
from openalex_pipeline.upload.manifest import (
    MANIFEST_OBJECT_NAME,
    UPLOAD_MANIFEST_SCHEMA,
)


def bucket_from_name(bucket_name: str) -> storage.Bucket:
    """Construct a GCS bucket handle using Application Default Credentials."""
    return storage.Client().bucket(bucket_name)


def gcs_updated_by_year(
    bucket: storage.Bucket,
    years: Iterable[int],
) -> dict[int, datetime | None]:
    """Return blob ``updated`` metadata for each bronze year in one listing."""
    expected = {year: gcs_object_name(year) for year in years}
    by_name = {blob.name: blob.updated for blob in bucket.list_blobs(prefix="bronze/")}
    return {year: by_name.get(name) for year, name in expected.items()}


def upload_manifest_uploaded_at(
    bucket: storage.Bucket,
    expected_years: Iterable[int],
) -> list[datetime]:
    """Return validated upload timestamps for exactly ``expected_years``.

    A converged pipeline must have one well-typed, non-null row per configured
    year. Absence, Parquet parse failures, schema drift, or completeness errors
    raise ``UploadManifestInvalid``. Only GCS ``NotFound`` and diagnosed Parquet
    failures are relabeled; authentication, network, and unexpected SDK errors
    propagate untouched.
    """
    blob = bucket.blob(MANIFEST_OBJECT_NAME)
    try:
        payload = blob.download_as_bytes()
    except NotFound as exc:
        raise UploadManifestInvalid(
            f"upload manifest {MANIFEST_OBJECT_NAME!r} is absent"
        ) from exc

    try:
        frame = pl.read_parquet(BytesIO(payload))
    except pl.exceptions.PolarsError as exc:
        raise UploadManifestInvalid(
            f"upload manifest {MANIFEST_OBJECT_NAME!r} is unreadable: {exc}"
        ) from exc

    expected_schema = pl.Schema(UPLOAD_MANIFEST_SCHEMA)
    if frame.schema != expected_schema:
        raise UploadManifestInvalid(
            f"upload manifest schema {frame.schema!r} != pinned {expected_schema!r}"
        )
    if frame.is_empty():
        raise UploadManifestInvalid("upload manifest is empty")

    years = frame["publication_year"].to_list()
    if len(years) != len(set(years)):
        raise UploadManifestInvalid("upload manifest contains duplicate years")
    expected = set(expected_years)
    actual = set(years)
    if actual != expected:
        raise UploadManifestInvalid(
            f"upload manifest year set {sorted(actual)} != expected {sorted(expected)}"
        )
    if frame["uploaded_at"].null_count() != 0:
        raise UploadManifestInvalid("upload manifest contains null uploaded_at values")
    return frame["uploaded_at"].to_list()


def bq_relation_metadata_by_name(
    project: str,
    dataset: str,
    relations: Iterable[DbtRelationSpec],
) -> dict[str, WarehouseRelationMetadata]:
    """Return explicit BigQuery existence and modification metadata."""
    client = bigquery.Client(project=project)
    result: dict[str, WarehouseRelationMetadata] = {}
    for relation in relations:
        table_id = f"{project}.{dataset}.{relation.name}"
        try:
            table = client.get_table(table_id)
        except NotFound:
            result[relation.name] = WarehouseRelationMetadata(False, None)
        else:
            result[relation.name] = WarehouseRelationMetadata(True, table.modified)
    return result
