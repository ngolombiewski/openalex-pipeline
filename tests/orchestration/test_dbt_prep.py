from contextlib import contextmanager
from pathlib import Path

import pytest

from openalex_pipeline.orchestration import dbt_prep


def test_prepare_runs_deps_only_when_packages_missing_and_always_parses(
    tmp_path: Path,
) -> None:
    project = tmp_path / "dbt"
    project.mkdir()
    calls: list[list[str]] = []

    dbt_prep.prepare_dbt_project(project, project, invoke_dbt=calls.append)

    assert calls[0][0] == "deps"
    assert calls[1][0] == "parse"
    assert calls[1][-2:] == ["--target", "prod"]

    (project / "dbt_packages").mkdir()
    calls.clear()
    dbt_prep.prepare_dbt_project(project, project, invoke_dbt=calls.append)

    assert [call[0] for call in calls] == ["parse"]


def test_prepare_parses_even_when_manifest_exists(tmp_path: Path) -> None:
    project = tmp_path / "dbt"
    (project / "dbt_packages").mkdir(parents=True)
    target = project / "target"
    target.mkdir()
    (target / "manifest.json").write_text("{}", encoding="utf-8")
    calls: list[list[str]] = []

    dbt_prep.prepare_dbt_project(project, project, invoke_dbt=calls.append)

    assert [call[0] for call in calls] == ["parse"]


@pytest.mark.parametrize(
    ("packages_present", "failing_command"),
    [(False, "deps"), (True, "parse")],
)
def test_prepare_propagates_dbt_failure(
    tmp_path: Path,
    packages_present: bool,
    failing_command: str,
) -> None:
    project = tmp_path / "dbt"
    project.mkdir()
    if packages_present:
        (project / "dbt_packages").mkdir()

    def fail(args: list[str]) -> None:
        if args[0] == failing_command:
            raise RuntimeError(f"dbt {failing_command} failed")

    with pytest.raises(RuntimeError, match=f"dbt {failing_command} failed"):
        dbt_prep.prepare_dbt_project(project, project, invoke_dbt=fail)


def test_prepare_runs_under_dedicated_lock(tmp_path: Path, monkeypatch) -> None:
    project = tmp_path / "dbt"
    (project / "dbt_packages").mkdir(parents=True)
    events: list[str] = []

    @contextmanager
    def fake_lock(path: Path):
        events.append(f"lock:{path.name}")
        yield
        events.append("unlock")

    monkeypatch.setattr(dbt_prep, "_prepare_lock", fake_lock)

    dbt_prep.prepare_dbt_project(
        project,
        project,
        invoke_dbt=lambda _args: events.append("parse"),
    )

    assert events == ["lock:.prepare.lock", "parse", "unlock"]
