"""Fixtures and fakes for the upload tests.

No cloud boundary is crossed: ``google.cloud.storage.Bucket``/``Blob`` are
replaced by in-memory fakes that record what was uploaded and let a test control
an object's ``updated``/``size`` metadata. The local side is a real tmp
directory holding real (tiny) Parquet files with controllable mtimes -- so the
skip decision runs against genuine ``stat().st_mtime`` values.

We test our logic, not the SDK.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import pytest

# A fixed POSIX mtime baseline so skip-logic tests can place an object's
# ``updated`` a controlled delta on either side of a local file's mtime.
BASE_MTIME = 1_700_000_000.0
BASE_MTIME_UTC = datetime.fromtimestamp(BASE_MTIME, tz=timezone.utc)

# The server-side timestamp a fake upload stamps onto a blob.
UPLOAD_TIME = datetime(2026, 6, 6, 12, 0, 0, tzinfo=timezone.utc)


class FakeBlob:
    """In-memory stand-in for a GCS Blob: records uploads, exposes metadata."""

    def __init__(self, name: str, bucket: "FakeBucket") -> None:
        self.name = name
        self._bucket = bucket
        self._present = False
        self.size: int | None = None
        self.updated: datetime | None = None
        self.uploaded_bytes: bytes | None = None
        self.uploaded_from: str | None = None

    def exists(self) -> bool:
        return self._present

    def reload(self) -> None:
        # Real SDK fetches metadata here; the fake already carries it.
        if not self._present:
            raise AssertionError(f"reload() on absent blob {self.name!r}")

    def upload_from_filename(self, filename: str) -> None:
        self.uploaded_from = filename
        self.size = os.path.getsize(filename)
        self.updated = self._bucket.upload_time
        self._present = True

    def upload_from_string(self, data: bytes, content_type: str | None = None) -> None:
        self.uploaded_bytes = data
        self.size = len(data)
        self.updated = self._bucket.upload_time
        self._present = True


class FakeBucket:
    """In-memory stand-in for a GCS Bucket. ``blob(name)`` is stable per name."""

    def __init__(self, name: str = "test-bucket", upload_time: datetime = UPLOAD_TIME) -> None:
        self.name = name
        self.upload_time = upload_time
        self._blobs: dict[str, FakeBlob] = {}

    def blob(self, name: str) -> FakeBlob:
        if name not in self._blobs:
            self._blobs[name] = FakeBlob(name, self)
        return self._blobs[name]

    def preset(self, name: str, *, size: int, updated: datetime) -> FakeBlob:
        """Pre-populate an already-existing object with metadata."""
        blob = self.blob(name)
        blob._present = True
        blob.size = size
        blob.updated = updated
        return blob


@pytest.fixture
def bronze_root(tmp_path: Path) -> Path:
    """Bronze input directory, created empty."""
    path = tmp_path / "bronze"
    path.mkdir()
    return path


@pytest.fixture
def bucket() -> FakeBucket:
    return FakeBucket()


def make_bronze_parquet(bronze_root: Path, year: int, mtime: float = BASE_MTIME) -> Path:
    """Write a tiny real Parquet for ``year`` and stamp its mtime."""
    path = bronze_root / f"{year}.parquet"
    pl.DataFrame({"id": [f"W{year}"]}).write_parquet(path)
    os.utime(path, (mtime, mtime))
    return path
