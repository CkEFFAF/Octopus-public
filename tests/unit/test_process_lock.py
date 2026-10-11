from __future__ import annotations

from pathlib import Path

import pytest

from octop.infra.utils.process_lock import ProcessAlreadyRunning, ProcessLock


def test_same_profile_is_exclusive_and_released_after_exit(tmp_path: Path) -> None:
    path = tmp_path / "profile" / "running.lock"
    with ProcessLock(path):
        with pytest.raises(ProcessAlreadyRunning, match="already in use"), ProcessLock(path):
            pytest.fail("second lock was acquired")
        with ProcessLock(tmp_path / "other.lock"):
            pass
    with ProcessLock(path):
        pass


def test_failed_host_start_releases_lock_before_next_try(tmp_path: Path) -> None:
    path = tmp_path / "host.lock"
    with pytest.raises(RuntimeError, match="failed start"), ProcessLock(path):
        raise RuntimeError("failed start")
    with ProcessLock(path):
        pass
