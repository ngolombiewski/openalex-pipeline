"""Upload single-year logic: discovery, skip decision, and one-file upload.

Imports nothing from manifest -- upload and derived state are sibling concerns;
the runner is the only place that touches both (mirroring bronze).

The GCS bucket is injected, never constructed here: callers pass a
``google.cloud.storage.Bucket``. This keeps every cloud touch behind one seam
the tests mock.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from google.cloud.storage import Bucket


def gcs_object_name(year: int) -> str:
    """The Hive-partitioned object name for a year, relative to the bucket.

    ``bronze/publication_year={year}/{year}.parquet`` -- the prefix exists
    solely for BigQuery partition pruning.
    """
    return f"bronze/publication_year={year}/{year}.parquet"


def gcs_uri(bucket_name: str, year: int) -> str:
    """The full ``gs://`` URI for a year's object."""
    return f"gs://{bucket_name}/{gcs_object_name(year)}"


def discover_years(bronze_root: Path) -> list[int]:
    """Every year with a bronze Parquet on disk, sorted ascending.

    Matches ``{year}.parquet`` where the stem is all digits. Deliberately
    excludes the derived ``_MANIFEST.parquet`` and any transient ``*.tmp``
    files mid-write in the bronze directory.
    """
    return sorted(
        int(p.stem)
        for p in bronze_root.glob("*.parquet")
        if p.stem.isdigit()
    )


def should_skip(local_mtime: float, blob_updated: datetime | None) -> bool:
    """Decide whether a year's upload can be skipped.

    Skip iff the object already exists AND its server-side ``updated`` timestamp
    is >= the local file's mtime. The comparison crosses two clock
    representations: ``local_mtime`` is a naive POSIX float from ``os.stat``,
    ``blob_updated`` is a tz-aware UTC datetime. We lift the float to tz-aware
    UTC so both sides are comparable.

    Args:
        local_mtime: The local Parquet's ``stat().st_mtime``.
        blob_updated: The GCS blob's ``updated``, or None if the object is
            absent.

    Returns:
        True to skip (object present and fresh); False to (re-)upload.
    """
    if blob_updated is None:
        return False
    return blob_updated >= datetime.fromtimestamp(local_mtime, tz=timezone.utc)


@dataclass
class YearUploadResult:
    """In-memory outcome of handling one year. Not persisted directly.

    Every field is sourced from live GCS blob metadata, so a run's results
    project the bucket's true state -- whether the year was uploaded or skipped
    this run. The manifest is built wholesale from these.

    file_size_bytes and uploaded_at come from ``blob.size`` / ``blob.updated``
    (UTC) after the blob's metadata is loaded.
    """

    year: int
    gcs_path: str
    uploaded: bool
    file_size_bytes: int
    uploaded_at: datetime


def upload_year(bucket: Bucket, bronze_root: Path, year: int) -> YearUploadResult:
    """Upload one year's Parquet unless an up-to-date object already exists.

    Resolves the blob, loads its metadata if present, and applies ``should_skip``.
    On upload, the freshly written blob is reloaded so the returned size and
    timestamp are the authoritative server-side values -- identical in source to
    the skipped path, which keeps the manifest a uniform projection of GCS state.

    Args:
        bucket: The target ``google.cloud.storage.Bucket``.
        bronze_root: Local directory holding ``{year}.parquet``.
        year: The publication year to upload.

    Returns:
        A YearUploadResult carrying the blob's path, size, and ``updated``
        timestamp, plus whether bytes were transferred this run.
    """
    local_path = bronze_root / f"{year}.parquet"
    blob = bucket.blob(gcs_object_name(year))

    if blob.exists():
        blob.reload()
        blob_updated = blob.updated
    else:
        blob_updated = None

    local_mtime = local_path.stat().st_mtime
    uploaded = not should_skip(local_mtime, blob_updated)

    if uploaded:
        blob.upload_from_filename(str(local_path))
        blob.reload()

    # size/updated are populated by reload() (skip path) or the upload+reload
    # above; the SDK types them Optional until then. bucket.name is set on any
    # real bucket. Loud if the SDK ever violates this.
    assert blob.size is not None and blob.updated is not None
    assert bucket.name is not None

    return YearUploadResult(
        year=year,
        gcs_path=gcs_uri(bucket.name, year),
        uploaded=uploaded,
        file_size_bytes=blob.size,
        uploaded_at=blob.updated,
    )
