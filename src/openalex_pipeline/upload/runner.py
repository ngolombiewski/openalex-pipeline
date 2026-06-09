"""Upload runner: upload every bronze year to GCS, then rebuild the manifest.

The only module that touches both core (per-year upload) and manifest (derived
state). The GCS bucket is injected so the cloud boundary stays behind one seam.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger

from .core import YearUploadResult, discover_years, upload_year
from .manifest import build_manifest, write_manifest

if TYPE_CHECKING:
    from google.cloud.storage import Bucket


def run(bronze_root: Path, bucket: Bucket) -> list[YearUploadResult]:
    """Upload every bronze year in `bronze_root`, then write the manifest.

    Discovers years from disk (no metadata passed from bronze), uploads each one
    -- skipping objects already up to date -- logging live per year, then rebuilds
    and uploads the manifest last so its presence signals a complete run.
    Returns the per-year results.
    """
    years = discover_years(bronze_root)
    results = []
    for year in years:
        result = upload_year(bucket, bronze_root, year)
        _log_year(result)
        results.append(result)

    manifest = build_manifest(results)
    uri = write_manifest(bucket, manifest)

    uploaded = sum(r.uploaded for r in results)
    skipped = len(results) - uploaded
    logger.info(
        f"manifest written: {uri} "
        f"({len(results)} year(s): {uploaded} uploaded, {skipped} skipped)"
    )
    return results


# --- Internal ---------------------------------------------------------------


def _log_year(result: YearUploadResult) -> None:
    """Log one year's outcome live: skipped, or uploaded with a human-readable size."""
    if result.uploaded:
        logger.info(
            f"{result.year}: uploaded -> {result.gcs_path} "
            f"({_format_size(result.file_size_bytes)})"
        )
    else:
        logger.info(f"{result.year}: skipped (up to date) -> {result.gcs_path}")


def _format_size(num_bytes: int) -> str:
    """Render a byte count as a short human-readable string."""
    size = float(num_bytes)
    for unit in ("B", "KB", "MB", "GB"):
        if size < 1024 or unit == "GB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} GB"
