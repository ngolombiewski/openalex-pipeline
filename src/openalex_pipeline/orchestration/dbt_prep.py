"""Deterministic dbt-manifest preparation for every definitions process."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
import fcntl
from pathlib import Path

from dbt.cli.main import dbtRunner

DbtInvoker = Callable[[list[str]], None]


def prepare_dbt_project(
    project_dir: Path,
    profiles_dir: Path,
    *,
    target: str = "prod",
    invoke_dbt: DbtInvoker | None = None,
) -> Path:
    """Prepare dependencies if absent and always parse a current manifest.

    Preparation is serialized on dbt/.prepare.lock because daemon and
    webserver processes may import definitions concurrently. Parse is always
    run after taking the lock, even when a manifest exists, so source changes
    cannot leave Dagster mapped from stale artifacts. dbt failures propagate
    loudly; successful preparation returns the expected manifest path.
    """
    invoke = invoke_dbt or _invoke_dbt
    project_dir = project_dir.resolve()
    profiles_dir = profiles_dir.resolve()
    lock_path = project_dir / ".prepare.lock"
    with _prepare_lock(lock_path):
        common = [
            "--project-dir",
            str(project_dir),
            "--profiles-dir",
            str(profiles_dir),
            "--target",
            target,
        ]
        if not (project_dir / "dbt_packages").is_dir():
            invoke(["deps", *common])
        invoke(["parse", *common])
    return project_dir / "target" / "manifest.json"


@contextmanager
def _prepare_lock(path: Path) -> Iterator[None]:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _invoke_dbt(args: list[str]) -> None:
    result = dbtRunner().invoke(args)
    if not result.success:
        detail = f": {result.exception}" if result.exception else ""
        raise RuntimeError(
            "dbt project preparation failed; activate the repository direnv "
            "environment before importing Dagster definitions"
            f"{detail}"
        )
