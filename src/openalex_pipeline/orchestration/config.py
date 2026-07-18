"""Runtime configuration shared by Dagster assets, jobs, and sensors.

This module resolves existing project environment variables into the small set
of paths and names orchestration needs. It does not introduce a Dagster-specific
configuration layer; the runners remain the owners of their own config.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path

from openalex_pipeline.extraction.settings import Settings

OPENALEX_GCS_BUCKET_ENV = "OPENALEX_GCS_BUCKET"
OPENALEX_GCP_PROJECT_ENV = "OPENALEX_GCP_PROJECT"

PROD_DATASET = "openalex_analytics"


@dataclass(frozen=True)
class OrchestrationConfig:
    """Resolved runtime config for one orchestration evaluation."""

    settings: Settings
    data_root: Path
    extract_root: Path
    bronze_root: Path
    years: list[int]
    bucket_name: str
    gcp_project: str
    prod_dataset: str = PROD_DATASET


def load_config() -> OrchestrationConfig:
    """Resolve config from the project environment variables.

    ``Settings`` resolves the one project data root and derives the extraction
    landing zone. Orchestration derives the bronze root from that same root;
    the filesystem lock helper receives the root and places its lock beside
    both local layer directories.

    Raises:
        RuntimeError: required non-extraction env vars are missing.
        pydantic.ValidationError: extraction ``Settings`` is invalid.
    """
    settings = Settings()  # type: ignore[call-arg]
    data_root = settings.data_root
    return OrchestrationConfig(
        settings=settings,
        data_root=data_root,
        extract_root=settings.data_dir,
        bronze_root=data_root / "bronze",
        years=settings.years,
        bucket_name=_required_env(OPENALEX_GCS_BUCKET_ENV),
        gcp_project=_required_env(OPENALEX_GCP_PROJECT_ENV),
    )


def _required_env(name: str) -> str:
    value = os.environ.get(name)
    if value:
        return value
    raise RuntimeError(f"{name} is required for Dagster orchestration")
