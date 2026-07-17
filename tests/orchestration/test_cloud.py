from datetime import datetime, timezone
from io import BytesIO
from typing import cast

from google.api_core.exceptions import NotFound
from google.cloud import storage
import polars as pl
import pytest

from openalex_pipeline.orchestration.cloud import upload_manifest_uploaded_at
from openalex_pipeline.orchestration.exceptions import UploadManifestInvalid
from openalex_pipeline.upload.manifest import UPLOAD_MANIFEST_SCHEMA


class _Blob:
    def __init__(self, payload: bytes | None = None, error: Exception | None = None):
        self.payload = payload
        self.error = error

    def download_as_bytes(self) -> bytes:
        if self.error:
            raise self.error
        if self.payload is None:
            raise NotFound("manifest absent")
        return self.payload


class _Bucket:
    def __init__(self, blob: _Blob):
        self._blob = blob

    def blob(self, _name: str) -> _Blob:
        return self._blob


def _bucket(blob: _Blob) -> storage.Bucket:
    return cast(storage.Bucket, _Bucket(blob))


def _parquet(rows: list[dict[str, object]], schema=UPLOAD_MANIFEST_SCHEMA) -> bytes:
    frame = pl.DataFrame(rows, schema=schema, orient="row")
    output = BytesIO()
    frame.write_parquet(output)
    return output.getvalue()


def _row(year: int, uploaded_at: datetime | None = None) -> dict[str, object]:
    return {
        "publication_year": year,
        "gcs_path": f"gs://bucket/{year}.parquet",
        "file_size_bytes": 10,
        "uploaded_at": uploaded_at or datetime(2026, 7, 1, tzinfo=timezone.utc),
    }


def test_upload_manifest_absent_raises() -> None:
    with pytest.raises(UploadManifestInvalid, match="absent"):
        upload_manifest_uploaded_at(_bucket(_Blob()), [2026])


def test_upload_manifest_unreadable_or_wrong_schema_raises() -> None:
    with pytest.raises(UploadManifestInvalid, match="unreadable"):
        upload_manifest_uploaded_at(_bucket(_Blob(b"not parquet")), [2026])

    wrong_schema = dict(UPLOAD_MANIFEST_SCHEMA)
    wrong_schema["publication_year"] = pl.String
    with pytest.raises(UploadManifestInvalid, match="schema"):
        upload_manifest_uploaded_at(
            _bucket(
                _Blob(
                    _parquet([{**_row(2026), "publication_year": "2026"}], wrong_schema)
                )
            ),
            [2026],
        )


@pytest.mark.parametrize(
    ("rows", "expected", "message"),
    [
        ([_row(2026)], [2025, 2026], "year set"),
        ([_row(2025), _row(2026)], [2026], "year set"),
        ([_row(2026), _row(2026)], [2026], "duplicate"),
        ([], [2026], "empty"),
    ],
)
def test_upload_manifest_requires_exact_unique_years(
    rows: list[dict[str, object]], expected: list[int], message: str
) -> None:
    with pytest.raises(UploadManifestInvalid, match=message):
        upload_manifest_uploaded_at(_bucket(_Blob(_parquet(rows))), expected)


def test_upload_manifest_rejects_null_uploaded_at() -> None:
    row = _row(2026)
    row["uploaded_at"] = None

    with pytest.raises(UploadManifestInvalid, match="null uploaded_at"):
        upload_manifest_uploaded_at(_bucket(_Blob(_parquet([row]))), [2026])


def test_upload_manifest_returns_well_formed_timestamps() -> None:
    first = datetime(2026, 7, 1, tzinfo=timezone.utc)
    second = datetime(2026, 7, 2, tzinfo=timezone.utc)

    assert upload_manifest_uploaded_at(
        _bucket(_Blob(_parquet([_row(2025, first), _row(2026, second)]))),
        [2025, 2026],
    ) == [first, second]


def test_upload_manifest_propagates_unexpected_client_errors() -> None:
    error = RuntimeError("credentials unavailable")

    with pytest.raises(RuntimeError, match="credentials unavailable"):
        upload_manifest_uploaded_at(_bucket(_Blob(error=error)), [2026])
