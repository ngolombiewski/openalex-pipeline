"""Filesystem serialization for Dagster computes over the local data chain."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum
import fcntl
from pathlib import Path

LOCK_FILE_NAME = ".orchestration.lock"


class LocalDataLockMode(Enum):
    """The two lock modes used by orchestration."""

    EXCLUSIVE = "exclusive"
    SHARED_NONBLOCKING = "shared_nonblocking"


@contextmanager
def local_data_lock(
    data_root: Path,
    mode: LocalDataLockMode,
) -> Iterator[bool]:
    """Acquire the orchestration lock and report whether it was acquired.

    Exclusive writers block until they acquire ``LOCK_EX`` and therefore
    always yield ``True``. Sensor readers attempt ``LOCK_SH | LOCK_NB`` and
    yield ``False`` immediately when a writer owns the lock. The data root is
    created first so a clean bootstrap has a lock location.
    """
    data_root.mkdir(parents=True, exist_ok=True)
    path = data_root / LOCK_FILE_NAME
    with path.open("a+b") as handle:
        operation = (
            fcntl.LOCK_EX
            if mode is LocalDataLockMode.EXCLUSIVE
            else fcntl.LOCK_SH | fcntl.LOCK_NB
        )
        try:
            fcntl.flock(handle.fileno(), operation)
        except BlockingIOError:
            if mode is LocalDataLockMode.EXCLUSIVE:
                raise
            yield False
            return

        try:
            yield True
        finally:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
