from multiprocessing import get_context
from pathlib import Path
import time
from typing import Any

from openalex_pipeline.orchestration.lock import LocalDataLockMode, local_data_lock


def _hold_lock(
    data_root: str,
    mode: LocalDataLockMode,
    acquired: Any,
    release: Any,
) -> None:
    with local_data_lock(Path(data_root), mode) as locked:
        assert locked
        acquired.set()
        release.wait(timeout=5)


def _acquire_and_release(
    data_root: str,
    mode: LocalDataLockMode,
    acquired: Any,
) -> None:
    with local_data_lock(Path(data_root), mode) as locked:
        assert locked
        acquired.set()


def test_second_exclusive_acquirer_blocks_until_release(tmp_path: Path) -> None:
    ctx = get_context("spawn")
    first_acquired, first_release = ctx.Event(), ctx.Event()
    second_acquired = ctx.Event()
    first = ctx.Process(
        target=_hold_lock,
        args=(
            str(tmp_path),
            LocalDataLockMode.EXCLUSIVE,
            first_acquired,
            first_release,
        ),
    )
    second = ctx.Process(
        target=_acquire_and_release,
        args=(str(tmp_path), LocalDataLockMode.EXCLUSIVE, second_acquired),
    )
    first.start()
    assert first_acquired.wait(timeout=2)
    second.start()
    assert not second_acquired.wait(timeout=0.2)
    first_release.set()
    assert second_acquired.wait(timeout=2)
    first.join(timeout=2)
    second.join(timeout=2)
    assert first.exitcode == second.exitcode == 0


def test_shared_nonblocking_fails_immediately_while_exclusive_held(
    tmp_path: Path,
) -> None:
    ctx = get_context("spawn")
    acquired, release = ctx.Event(), ctx.Event()
    holder = ctx.Process(
        target=_hold_lock,
        args=(str(tmp_path), LocalDataLockMode.EXCLUSIVE, acquired, release),
    )
    holder.start()
    assert acquired.wait(timeout=2)

    started = time.monotonic()
    with local_data_lock(tmp_path, LocalDataLockMode.SHARED_NONBLOCKING) as locked:
        assert not locked
    assert time.monotonic() - started < 0.5

    release.set()
    holder.join(timeout=2)
    assert holder.exitcode == 0


def test_exclusive_writer_blocks_while_shared_reader_held(tmp_path: Path) -> None:
    ctx = get_context("spawn")
    reader_acquired, reader_release = ctx.Event(), ctx.Event()
    writer_acquired = ctx.Event()
    reader = ctx.Process(
        target=_hold_lock,
        args=(
            str(tmp_path),
            LocalDataLockMode.SHARED_NONBLOCKING,
            reader_acquired,
            reader_release,
        ),
    )
    writer = ctx.Process(
        target=_acquire_and_release,
        args=(str(tmp_path), LocalDataLockMode.EXCLUSIVE, writer_acquired),
    )
    reader.start()
    assert reader_acquired.wait(timeout=2)
    writer.start()
    assert not writer_acquired.wait(timeout=0.2)
    reader_release.set()
    assert writer_acquired.wait(timeout=2)
    reader.join(timeout=2)
    writer.join(timeout=2)
    assert reader.exitcode == writer.exitcode == 0
