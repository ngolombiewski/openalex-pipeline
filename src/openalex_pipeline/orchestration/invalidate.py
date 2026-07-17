"""Durable request/executor protocol for current-year invalidation."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
import os
from pathlib import Path
import shutil

from openalex_pipeline.extraction.models import YearState
from openalex_pipeline.extraction.storage import classify_year
from openalex_pipeline.orchestration.exceptions import TombstoneCorruption

TOMBSTONE_PREFIX = "_INVALIDATING_"


class InvalidationRequestStatus(Enum):
    """Outcome of requesting one publication-year invalidation."""

    REQUESTED = "requested"
    SKIPPED_PENDING = "skipped_pending"
    SKIPPED_IN_PROGRESS = "skipped_in_progress"
    SKIPPED_ABSENT = "skipped_absent"


@dataclass(frozen=True)
class InvalidationRequestResult:
    """Immutable result of the non-destructive monthly request step."""

    year: int
    status: InvalidationRequestStatus


@dataclass(frozen=True)
class InvalidationExecutionResult:
    """Immutable result of executing one durable invalidation tombstone.

    The booleans report which local artifacts still existed and were deleted
    by this invocation. One result is returned for each valid tombstone.
    """

    year: int
    deleted_extraction: bool
    deleted_bronze: bool


def request_year_invalidation(
    extract_root: Path,
    year: int,
    query: str,
) -> InvalidationRequestResult:
    """Durably request invalidation without deleting any pipeline artifact.

    An existing tombstone wins over an absent year directory because it means
    execution is already pending. Otherwise only a COMPLETE year may be
    requested. In-progress/FRESH existing directories and absent directories
    are explicit no-ops. Corruption and query mismatch propagate from the
    extraction classifier.
    """
    marker = _tombstone_path(extract_root, year)
    if marker.exists():
        return InvalidationRequestResult(
            year, InvalidationRequestStatus.SKIPPED_PENDING
        )

    year_dir = extract_root / str(year)
    if not year_dir.exists():
        return InvalidationRequestResult(year, InvalidationRequestStatus.SKIPPED_ABSENT)

    status = classify_year(extract_root, year, query)
    if status.state is not YearState.COMPLETE:
        return InvalidationRequestResult(
            year, InvalidationRequestStatus.SKIPPED_IN_PROGRESS
        )

    try:
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o644)
    except FileExistsError:
        return InvalidationRequestResult(
            year, InvalidationRequestStatus.SKIPPED_PENDING
        )
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    _fsync_directory(extract_root)
    return InvalidationRequestResult(year, InvalidationRequestStatus.REQUESTED)


def resume_pending_invalidations(
    extract_root: Path,
    bronze_root: Path,
    expected_years: list[int],
) -> list[InvalidationExecutionResult]:
    """Execute every valid pending invalidation in interruption-safe order.

    A tombstone authorizes unconditional deletion: bronze parquet first, then
    the extraction year directory, then the marker. Directory fsyncs ensure
    the marker cannot durably disappear before the deletions it authorizes.
    Invalid tombstone names or years raise ``TombstoneCorruption`` before any
    deletion begins.
    """
    pending = pending_invalidation_years(extract_root, expected_years)
    results: list[InvalidationExecutionResult] = []
    for year in pending:
        marker = _tombstone_path(extract_root, year)
        parquet = bronze_root / f"{year}.parquet"
        year_dir = extract_root / str(year)

        deleted_bronze = parquet.exists()
        if deleted_bronze:
            parquet.unlink()

        deleted_extraction = year_dir.exists()
        if deleted_extraction:
            shutil.rmtree(year_dir)

        if bronze_root.exists():
            _fsync_directory(bronze_root)
        _fsync_directory(extract_root)
        marker.unlink()
        _fsync_directory(extract_root)
        results.append(
            InvalidationExecutionResult(
                year=year,
                deleted_extraction=deleted_extraction,
                deleted_bronze=deleted_bronze,
            )
        )
    return results


def pending_invalidation_years(
    extract_root: Path,
    expected_years: list[int],
) -> list[int]:
    """Return sorted in-scope tombstone years; reject invalid markers loudly."""
    if not extract_root.exists():
        return []

    allowed = set(expected_years)
    pending: list[int] = []
    for marker in sorted(extract_root.glob(f"{TOMBSTONE_PREFIX}*")):
        suffix = marker.name.removeprefix(TOMBSTONE_PREFIX)
        try:
            year = int(suffix)
        except ValueError as exc:
            raise TombstoneCorruption(
                f"invalid invalidation tombstone {marker.name!r}: year is not an integer"
            ) from exc
        if suffix != str(year) or not marker.is_file():
            raise TombstoneCorruption(
                f"invalid invalidation tombstone {marker.name!r}: "
                "expected a canonical regular marker file"
            )
        if year not in allowed:
            raise TombstoneCorruption(
                f"invalid invalidation tombstone {marker.name!r}: "
                f"year {year} is outside configured bounds"
            )
        pending.append(year)
    return pending


def _tombstone_path(extract_root: Path, year: int) -> Path:
    return extract_root / f"{TOMBSTONE_PREFIX}{year}"


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
