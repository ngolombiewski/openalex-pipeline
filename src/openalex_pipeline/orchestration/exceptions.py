"""Typed failures diagnosed by the orchestration layer."""


class OrchestrationError(Exception):
    """Base class for known orchestration failures."""


class TombstoneCorruption(OrchestrationError):
    """An invalidation tombstone is malformed or outside configured bounds."""


class UploadManifestInvalid(OrchestrationError):
    """The converged upload manifest is absent, unreadable, or invalid."""


class UnsupportedDbtMaterialization(OrchestrationError):
    """A dbt model uses a physical materialization outside table/view."""


class WarehouseMetadataInvalid(OrchestrationError):
    """BigQuery metadata cannot establish warehouse completeness/freshness."""
