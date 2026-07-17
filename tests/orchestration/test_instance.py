from pathlib import Path
import shutil

from dagster import DagsterInstance


REPO_ROOT = Path(__file__).resolve().parents[2]


def test_tracked_instance_config_enables_automatic_run_retries(tmp_path: Path) -> None:
    shutil.copy2(REPO_ROOT / "dagster.yaml", tmp_path / "dagster.yaml")

    instance = DagsterInstance.from_config(str(tmp_path))
    try:
        assert instance.run_retries_enabled
    finally:
        instance.dispose()
