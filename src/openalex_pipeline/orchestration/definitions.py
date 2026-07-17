"""Dagster definitions for the OpenAlex pipeline.

Importing this module is a startup action: it prepares a current prod-target
dbt manifest before Dagster reads the asset graph.
"""

from __future__ import annotations

from pathlib import Path

from dagster import (
    AssetKey,
    AssetSelection,
    DagsterRunStatus,
    DefaultScheduleStatus,
    DefaultSensorStatus,
    Definitions,
    MaterializeResult,
    RunRequest,
    RunsFilter,
    ScheduleDefinition,
    SkipReason,
    asset,
    define_asset_job,
    job,
    op,
    resource,
    sensor,
)
from dagster_dbt import DagsterDbtTranslator, DbtCliResource, DbtProject, dbt_assets

from openalex_pipeline.bronze import runner as bronze_runner
from openalex_pipeline.extraction import runner as extraction_runner
from openalex_pipeline.extraction.runner import canonical_query
from openalex_pipeline.orchestration import cloud
from openalex_pipeline.orchestration.config import load_config
from openalex_pipeline.orchestration.convergence import (
    dbt_model_relations,
    is_converged,
    warehouse_is_stale,
)
from openalex_pipeline.orchestration.dbt_prep import prepare_dbt_project
from openalex_pipeline.orchestration.invalidate import (
    request_year_invalidation,
    resume_pending_invalidations,
)
from openalex_pipeline.orchestration.lock import LocalDataLockMode, local_data_lock
from openalex_pipeline.upload import runner as upload_runner

REPO_ROOT = Path(__file__).resolve().parents[3]
DBT_PROJECT_DIR = REPO_ROOT / "dbt"
DBT_PROJECT = DbtProject(
    project_dir=DBT_PROJECT_DIR,
    profiles_dir=DBT_PROJECT_DIR,
    target="prod",
)
DBT_MANIFEST_PATH = prepare_dbt_project(
    DBT_PROJECT_DIR,
    DBT_PROJECT_DIR,
    target="prod",
)


class OpenAlexDbtTranslator(DagsterDbtTranslator):
    """Connect the dbt bronze source to the upstream GCS upload asset."""

    def get_asset_key(self, dbt_resource_props):
        if (
            dbt_resource_props.get("resource_type") == "source"
            and dbt_resource_props.get("source_name") == "bronze"
            and dbt_resource_props.get("name") == "bronze_external"
        ):
            return AssetKey("bronze_gcs")
        return super().get_asset_key(dbt_resource_props)


DBT_TRANSLATOR = OpenAlexDbtTranslator()


@resource
def gcs_bucket_resource(_):
    """Return the configured GCS bucket handle."""
    return cloud.bucket_from_name(load_config().bucket_name)


@asset
def extracted_jsonl() -> MaterializeResult:
    """Run extraction after executing durable invalidation requests.

    completed_shard_records_total is the lifetime record total stored in every
    completed shard visible to this invocation. It is not a per-run extraction
    delta: skipped shards contribute their persisted totals, while an incomplete
    daily-limit shard is absent from outcomes.
    """
    cfg = load_config()
    with local_data_lock(cfg.data_root, LocalDataLockMode.EXCLUSIVE):
        resume_pending_invalidations(
            cfg.extract_root,
            cfg.bronze_root,
            cfg.years,
        )
        report = extraction_runner.run(cfg.settings)

    completed = [
        outcome for outcome in report.outcomes if outcome.status == "completed"
    ]
    skipped = [outcome for outcome in report.outcomes if outcome.status == "skipped"]
    years = [outcome.year for outcome in report.outcomes]
    return MaterializeResult(
        metadata={
            "status": report.status,
            "stopped_year": report.stopped_year,
            "years_completed": len(completed),
            "years_skipped": len(skipped),
            "completed_shard_records_total": sum(
                outcome.report.records_fetched for outcome in report.outcomes
            ),
            "first_year": min(years) if years else None,
            "last_year": max(years) if years else None,
        }
    )


@asset(deps=[extracted_jsonl])
def bronze_parquet() -> MaterializeResult:
    """Run the local bronze sweep and report its resulting manifest state."""
    cfg = load_config()
    with local_data_lock(cfg.data_root, LocalDataLockMode.EXCLUSIVE):
        manifest = bronze_runner.run(cfg.extract_root, cfg.bronze_root, cfg.years)

    status_counts = (
        manifest.group_by("status").len().to_dict(as_series=False)
        if "status" in manifest.columns
        else {"status": [], "len": []}
    )
    return MaterializeResult(
        metadata={
            "years_configured": len(cfg.years),
            "manifest_years_total": manifest.height,
            "statuses": dict(zip(status_counts["status"], status_counts["len"])),
        }
    )


@asset(deps=[bronze_parquet], required_resource_keys={"gcs_bucket"})
def bronze_gcs(context) -> MaterializeResult:
    """Upload local bronze parquet and report per-invocation transfer work."""
    cfg = load_config()
    with local_data_lock(cfg.data_root, LocalDataLockMode.EXCLUSIVE):
        results = upload_runner.run(cfg.bronze_root, context.resources.gcs_bucket)

    uploaded = [result for result in results if result.uploaded]
    return MaterializeResult(
        metadata={
            "years_considered": len(results),
            "uploaded": len(uploaded),
            "skipped": len(results) - len(uploaded),
            "bytes_uploaded": sum(result.file_size_bytes for result in uploaded),
        }
    )


@dbt_assets(
    manifest=DBT_MANIFEST_PATH,
    project=DBT_PROJECT,
    dagster_dbt_translator=DBT_TRANSLATOR,
)
def openalex_dbt_assets(
    context,
    dbt: DbtCliResource,
):
    """Build prod dbt models and tests."""
    yield from dbt.cli(
        ["build"],
        context=context,
        dagster_dbt_translator=DBT_TRANSLATOR,
    ).stream()


local_sweep_job = define_asset_job(
    "local_sweep",
    selection=AssetSelection.assets(extracted_jsonl, bronze_parquet, bronze_gcs),
)

warehouse_build_job = define_asset_job(
    "warehouse_build",
    selection=AssetSelection.assets(openalex_dbt_assets),
)


@op
def invalidate_refresh_year_op() -> dict[str, object]:
    """Durably request refresh of the configured current year."""
    cfg = load_config()
    year = cfg.settings.end_year
    query = canonical_query(cfg.settings.filter, year)
    with local_data_lock(cfg.data_root, LocalDataLockMode.EXCLUSIVE):
        result = request_year_invalidation(cfg.extract_root, year, query)
    return {"year": result.year, "status": result.status.value}


@job
def invalidate_refresh_year():
    invalidate_refresh_year_op()


local_sweep_schedule = ScheduleDefinition(
    job=local_sweep_job,
    cron_schedule="0 4 * * *",
    execution_timezone="Europe/Berlin",
    default_status=DefaultScheduleStatus.RUNNING,
)

invalidate_refresh_year_schedule = ScheduleDefinition(
    job=invalidate_refresh_year,
    cron_schedule="0 3 1 * *",
    execution_timezone="Europe/Berlin",
    default_status=DefaultScheduleStatus.RUNNING,
)


@sensor(
    job=warehouse_build_job,
    minimum_interval_seconds=4 * 60 * 60,
    default_status=DefaultSensorStatus.RUNNING,
)
def warehouse_staleness_sensor(context):
    """Request one bounded-retry prod build per converged upload state."""
    if _warehouse_build_in_progress(context.instance):
        return SkipReason("warehouse_build already in progress")

    cfg = load_config()
    bucket = cloud.bucket_from_name(cfg.bucket_name)
    with local_data_lock(
        cfg.data_root,
        LocalDataLockMode.SHARED_NONBLOCKING,
    ) as acquired:
        if not acquired:
            return SkipReason("local pipeline mutation in progress")
        gcs_updates = cloud.gcs_updated_by_year(bucket, cfg.years)
        if not is_converged(
            cfg.extract_root,
            cfg.bronze_root,
            cfg.years,
            cfg.settings.filter,
            gcs_updates,
        ):
            return SkipReason("local/GCS pipeline is not converged")

    relations = dbt_model_relations(DBT_MANIFEST_PATH)
    uploaded_at = cloud.upload_manifest_uploaded_at(bucket, cfg.years)
    relation_metadata = cloud.bq_relation_metadata_by_name(
        cfg.gcp_project,
        cfg.prod_dataset,
        relations,
    )
    if not warehouse_is_stale(uploaded_at, relation_metadata, relations):
        return SkipReason("warehouse is fresh")

    latest_upload = max(uploaded_at)
    return RunRequest(
        run_key=f"warehouse_build:{latest_upload.isoformat()}",
        tags={
            "reason": "warehouse_stale",
            "dagster/max_retries": "3",
        },
    )


def _warehouse_build_in_progress(instance) -> bool:
    runs = instance.get_runs(
        filters=RunsFilter(
            job_name="warehouse_build",
            statuses=[
                DagsterRunStatus.QUEUED,
                DagsterRunStatus.STARTING,
                DagsterRunStatus.STARTED,
            ],
        ),
        limit=1,
    )
    return bool(runs)


defs = Definitions(
    assets=[
        extracted_jsonl,
        bronze_parquet,
        bronze_gcs,
        openalex_dbt_assets,
    ],
    jobs=[
        local_sweep_job,
        warehouse_build_job,
        invalidate_refresh_year,
    ],
    schedules=[
        local_sweep_schedule,
        invalidate_refresh_year_schedule,
    ],
    sensors=[warehouse_staleness_sensor],
    resources={
        "gcs_bucket": gcs_bucket_resource,
        "dbt": DbtCliResource(
            project_dir=DBT_PROJECT,
            profiles_dir=DBT_PROJECT_DIR,
            target="prod",
        ),
    },
)
