from contextlib import contextmanager
from datetime import datetime, timezone
import os
from pathlib import Path
import shutil
from types import SimpleNamespace
import subprocess
import sys
from typing import Any, cast

from dagster import (
    DefaultScheduleStatus,
    DefaultSensorStatus,
    Definitions,
    RunRequest,
    SkipReason,
)
import polars as pl
import pytest

from openalex_pipeline.extraction.models import RunReport, YearOutcome, YearReport
from openalex_pipeline.orchestration import definitions
from openalex_pipeline.orchestration.lock import LocalDataLockMode
from openalex_pipeline.orchestration.models import (
    DbtRelationSpec,
    WarehouseRelationMetadata,
)
from openalex_pipeline.upload.core import YearUploadResult


REPO_ROOT = Path(__file__).resolve().parents[2]


def _config(tmp_path: Path):
    settings = SimpleNamespace(
        end_year=2026,
        filter="primary_topic.field.id:17",
        years=[2025, 2026],
    )
    return SimpleNamespace(
        settings=settings,
        data_root=tmp_path,
        extract_root=tmp_path / "extract",
        bronze_root=tmp_path / "bronze",
        years=[2025, 2026],
        bucket_name="bucket",
        gcp_project="project",
        prod_dataset="dataset",
    )


def _recording_lock(events: list[str]):
    @contextmanager
    def lock(_root: Path, mode: LocalDataLockMode):
        events.append(f"lock:{mode.value}")
        yield True
        events.append("unlock")

    return lock


def _year_report(year: int, records: int) -> YearReport:
    return YearReport(
        query="query",
        year=year,
        started_at="2026-07-01T00:00:00Z",
        completed_at="2026-07-01T01:00:00Z",
        expected_count=records,
        records_fetched=records,
        page_count=1,
        count_mismatch=False,
    )


def test_extracted_jsonl_executes_pending_invalidations_before_runner(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = _config(tmp_path)
    events: list[str] = []
    report = RunReport(
        outcomes=[
            YearOutcome(2025, "skipped", _year_report(2025, 10)),
            YearOutcome(2026, "completed", _year_report(2026, 3)),
        ],
        status="complete",
    )
    monkeypatch.setattr(definitions, "load_config", lambda: cfg)
    monkeypatch.setattr(definitions, "local_data_lock", _recording_lock(events))
    monkeypatch.setattr(
        definitions,
        "resume_pending_invalidations",
        lambda *args: events.append(f"resume:{args[2]}"),
    )
    monkeypatch.setattr(
        definitions.extraction_runner,
        "run",
        lambda settings: events.append(f"extract:{settings.end_year}") or report,
    )

    result = cast(Any, definitions.extracted_jsonl).op.compute_fn.decorated_fn()

    assert events == [
        "lock:exclusive",
        "resume:[2025, 2026]",
        "extract:2026",
        "unlock",
    ]
    assert result.metadata == {
        "status": "complete",
        "stopped_year": None,
        "years_completed": 1,
        "years_skipped": 1,
        "completed_shard_records_total": 13,
        "first_year": 2025,
        "last_year": 2026,
    }


def test_bronze_parquet_calls_runner_under_exclusive_lock(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = _config(tmp_path)
    events: list[str] = []
    manifest = pl.DataFrame(
        {"status": ["ingested", "pending"], "publication_year": [2025, 2026]}
    )
    monkeypatch.setattr(definitions, "load_config", lambda: cfg)
    monkeypatch.setattr(definitions, "local_data_lock", _recording_lock(events))
    monkeypatch.setattr(
        definitions.bronze_runner,
        "run",
        lambda *args: events.append(f"bronze:{args}") or manifest,
    )

    result = cast(Any, definitions.bronze_parquet).op.compute_fn.decorated_fn()

    assert events[0] == "lock:exclusive"
    assert events[1] == f"bronze:{(cfg.extract_root, cfg.bronze_root, cfg.years)}"
    assert events[2] == "unlock"
    assert result.metadata == {
        "years_configured": 2,
        "manifest_years_total": 2,
        "statuses": {"ingested": 1, "pending": 1},
    }


def test_bronze_gcs_reports_only_bytes_uploaded_this_run(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = _config(tmp_path)
    events: list[str] = []
    timestamp = datetime(2026, 7, 1, tzinfo=timezone.utc)
    results = [
        YearUploadResult(2025, "gs://bucket/2025", False, 100, timestamp),
        YearUploadResult(2026, "gs://bucket/2026", True, 20, timestamp),
    ]
    bucket = object()
    context = SimpleNamespace(resources=SimpleNamespace(gcs_bucket=bucket))
    monkeypatch.setattr(definitions, "load_config", lambda: cfg)
    monkeypatch.setattr(definitions, "local_data_lock", _recording_lock(events))
    monkeypatch.setattr(
        definitions.upload_runner,
        "run",
        lambda *args: events.append(f"upload:{args}") or results,
    )

    result = cast(Any, definitions.bronze_gcs).op.compute_fn.decorated_fn(context)

    assert events == [
        "lock:exclusive",
        f"upload:{(cfg.bronze_root, bucket)}",
        "unlock",
    ]
    assert result.metadata == {
        "years_considered": 2,
        "uploaded": 1,
        "skipped": 1,
        "bytes_uploaded": 20,
    }


def test_invalidation_op_requests_under_exclusive_lock(
    tmp_path: Path, monkeypatch
) -> None:
    cfg = _config(tmp_path)
    events: list[str] = []
    request_result = SimpleNamespace(
        year=2026, status=SimpleNamespace(value="requested")
    )
    monkeypatch.setattr(definitions, "load_config", lambda: cfg)
    monkeypatch.setattr(definitions, "local_data_lock", _recording_lock(events))
    monkeypatch.setattr(
        definitions,
        "request_year_invalidation",
        lambda *args: events.append(f"request:{args}") or request_result,
    )

    result = cast(Any, definitions.invalidate_refresh_year_op).compute_fn.decorated_fn()

    assert events[0] == "lock:exclusive"
    assert events[1].startswith(f"request:({cfg.extract_root!r}, 2026,")
    assert events[2] == "unlock"
    assert result == {"year": 2026, "status": "requested"}


def _sensor_result(
    monkeypatch, tmp_path: Path, *, converged=True, stale=True, locked=True
) -> Any:
    cfg = _config(tmp_path)
    upload = datetime(2026, 7, 17, 12, tzinfo=timezone.utc)
    relations = [DbtRelationSpec("stg_works", "table")]
    monkeypatch.setattr(definitions, "load_config", lambda: cfg)
    monkeypatch.setattr(definitions, "_warehouse_build_in_progress", lambda _i: False)

    @contextmanager
    def lock(_root, _mode):
        yield locked

    monkeypatch.setattr(definitions, "local_data_lock", lock)
    monkeypatch.setattr(definitions.cloud, "bucket_from_name", lambda _name: object())
    monkeypatch.setattr(
        definitions.cloud,
        "gcs_updated_by_year",
        lambda _bucket, _years: {2025: upload, 2026: upload},
    )
    monkeypatch.setattr(definitions, "is_converged", lambda *args: converged)
    monkeypatch.setattr(definitions, "dbt_model_relations", lambda _path: relations)
    monkeypatch.setattr(
        definitions.cloud,
        "upload_manifest_uploaded_at",
        lambda _bucket, _years: [upload],
    )
    monkeypatch.setattr(
        definitions.cloud,
        "bq_relation_metadata_by_name",
        lambda *_args: {"stg_works": WarehouseRelationMetadata(True, upload)},
    )
    monkeypatch.setattr(definitions, "warehouse_is_stale", lambda *args: stale)
    context = SimpleNamespace(instance=object())
    return cast(Any, definitions.warehouse_staleness_sensor)._raw_fn(context)


def test_sensor_run_request_has_stable_upload_key_and_bounded_retries(
    tmp_path: Path, monkeypatch
) -> None:
    first = _sensor_result(monkeypatch, tmp_path)
    second = _sensor_result(monkeypatch, tmp_path)

    assert isinstance(first, RunRequest)
    assert first.run_key == "warehouse_build:2026-07-17T12:00:00+00:00"
    assert first.tags["dagster/max_retries"] == "3"
    assert second.run_key == first.run_key


def test_sensor_key_changes_for_new_upload(tmp_path: Path, monkeypatch) -> None:
    first = _sensor_result(monkeypatch, tmp_path)
    newer = datetime(2026, 7, 18, 12, tzinfo=timezone.utc)
    monkeypatch.setattr(
        definitions.cloud,
        "upload_manifest_uploaded_at",
        lambda _bucket, _years: [newer],
    )

    second = cast(Any, definitions.warehouse_staleness_sensor)._raw_fn(
        SimpleNamespace(instance=object())
    )

    assert first.run_key != second.run_key


@pytest.mark.parametrize(
    ("converged", "stale", "message"),
    [
        (False, True, "local/GCS pipeline is not converged"),
        (True, False, "warehouse is fresh"),
    ],
)
def test_sensor_skip_paths(
    tmp_path: Path,
    monkeypatch,
    converged: bool,
    stale: bool,
    message: str,
) -> None:
    result = _sensor_result(monkeypatch, tmp_path, converged=converged, stale=stale)

    assert isinstance(result, SkipReason)
    assert result.skip_message == message


def test_sensor_skips_run_in_progress() -> None:
    instance = SimpleNamespace(get_runs=lambda **_kwargs: [object()])
    result = cast(Any, definitions.warehouse_staleness_sensor)._raw_fn(
        SimpleNamespace(instance=instance)
    )

    assert isinstance(result, SkipReason)
    assert result.skip_message == "warehouse_build already in progress"


def test_sensor_skips_immediately_when_shared_lock_unavailable(
    tmp_path: Path, monkeypatch
) -> None:
    result = _sensor_result(monkeypatch, tmp_path, locked=False)

    assert isinstance(result, SkipReason)
    assert result.skip_message == "local pipeline mutation in progress"


def test_automations_default_to_running() -> None:
    assert (
        definitions.local_sweep_schedule.default_status is DefaultScheduleStatus.RUNNING
    )
    assert (
        definitions.invalidate_refresh_year_schedule.default_status
        is DefaultScheduleStatus.RUNNING
    )
    assert (
        definitions.warehouse_staleness_sensor.default_status
        is DefaultSensorStatus.RUNNING
    )


def test_definitions_loadable() -> None:
    Definitions.validate_loadable(definitions.defs)


def test_clean_checkout_import_prepares_prod_manifest(tmp_path: Path) -> None:
    shutil.copytree(REPO_ROOT / "src", tmp_path / "src")
    shutil.copytree(
        REPO_ROOT / "dbt",
        tmp_path / "dbt",
        ignore=shutil.ignore_patterns("target", "logs", ".prepare.lock"),
    )
    assert not (tmp_path / "dbt" / "target").exists()

    env = os.environ.copy()
    env["PYTHONPATH"] = str(tmp_path / "src")
    completed = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "from openalex_pipeline.orchestration.definitions import defs; "
                "from dagster import Definitions; Definitions.validate_loadable(defs)"
            ),
        ],
        cwd=tmp_path,
        env=env,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert completed.returncode == 0, completed.stderr
    assert (tmp_path / "dbt" / "target" / "manifest.json").exists()
