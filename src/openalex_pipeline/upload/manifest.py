"""Upload manifest: derived, never authoritative.

Rebuilt wholesale from the run's YearUploadResults (themselves projections of
live GCS blob metadata) every run. Imports core only for the result type; the
runner is the only module that touches both core and manifest.

The manifest lives in its own ``upload/`` prefix on GCS -- a sibling to
``bronze/``, deliberately outside the ``bronze/publication_year=*/`` tree that
BigQuery globs as Hive-partitioned, so it can never be mistaken for a partition.
"""

from __future__ import annotations

import io
from typing import TYPE_CHECKING

import polars as pl

from .core import YearUploadResult

if TYPE_CHECKING:
    from google.cloud.storage import Bucket

MANIFEST_OBJECT_NAME = "upload/_MANIFEST.parquet"

UPLOAD_MANIFEST_SCHEMA: dict[str, pl.DataType | type[pl.DataType]] = {
    "publication_year": pl.Int64,
    "gcs_path": pl.String,
    "file_size_bytes": pl.Int64,
    "uploaded_at": pl.Datetime("us", "UTC"),
}
"""Column order and dtypes of the upload manifest. uploaded_at is the blob's
server-side ``updated``, in UTC."""


def build_manifest(results: list[YearUploadResult]) -> pl.DataFrame:
    """Build the manifest DataFrame: one row per uploaded-or-skipped year.

    Purely derived: every value comes from a YearUploadResult, which carries
    live GCS blob metadata. The manifest is never read back.
    """
    rows = [
        {
            "publication_year": r.year,
            "gcs_path": r.gcs_path,
            "file_size_bytes": r.file_size_bytes,
            "uploaded_at": r.uploaded_at,
        }
        for r in results
    ]
    return pl.DataFrame(rows, schema=UPLOAD_MANIFEST_SCHEMA, orient="row")


def write_manifest(bucket: Bucket, manifest: pl.DataFrame) -> str:
    """Serialize the manifest to Parquet and upload it to GCS. Returns the URI.

    Written to ``upload/_MANIFEST.parquet`` and uploaded last by the runner, so
    its presence signals a complete run. Serialized in memory -- the manifest is
    small (one row per year) and never needs a local temp file.
    """
    buf = io.BytesIO()
    manifest.write_parquet(buf)
    blob = bucket.blob(MANIFEST_OBJECT_NAME)
    blob.upload_from_string(buf.getvalue(), content_type="application/octet-stream")
    return f"gs://{bucket.name}/{MANIFEST_OBJECT_NAME}"
