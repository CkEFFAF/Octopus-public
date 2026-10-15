"""Real detached Jobs survive executor shutdown and retain exact receipts."""

from __future__ import annotations

import asyncio
import base64
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

import psutil
import pytest

from octop.infra.devices.executor import DeviceExecutor
from octop.infra.devices.jobs import (
    JobSupervisor,
    process_identity,
    same_process,
    write_state,
)


def test_job_receipts_survive_a_brief_windows_reader_lock(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    write_state(path, {"status": "running"})
    with ThreadPoolExecutor() as worker:
        with path.open() as previous:
            writing = worker.submit(write_state, path, {"status": "completed"})
            time.sleep(0.05)
            assert '"running"' in previous.read()
        writing.result(timeout=2)
    assert '"completed"' in path.read_text()


async def observe(supervisor: JobSupervisor, job_id: str, statuses: set[str]) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + 15
    while asyncio.get_running_loop().time() < deadline:
        state = await asyncio.to_thread(supervisor.status, job_id)
        if state["status"] in statuses:
            return state
        await asyncio.sleep(0.1)
    raise AssertionError(f"Job did not reach {statuses}: {state}")


async def test_job_survives_executor_shutdown_and_supervisor_recreation(tmp_path: Path) -> None:
    executor = DeviceExecutor(
        ["command_exec", "files_read"],
        [],
        trust_mode="owner",
        working_dir=str(tmp_path),
        state_dir=tmp_path / "state",
    )
    params = {
        "argv": [
            sys.executable,
            "-u",
            "-c",
            "import time; print('started', flush=True); time.sleep(3); print('finished', flush=True)",
        ],
        "idempotency_key": "survives-reconnect",
    }
    started = await executor.execute(
        "submit", "jobs.start", params, grant_version=0, permissions=["command_exec"]
    )
    supervisor = JobSupervisor(tmp_path / "state" / "jobs")
    job_id = started["job_id"]
    try:
        running = await observe(supervisor, job_id, {"running"})
        await executor.close()
        assert same_process(running["process"]) is not None
        recreated = JobSupervisor(tmp_path / "state" / "jobs")
        retried = await asyncio.to_thread(recreated.start, params, tmp_path)
        assert retried["job_id"] == job_id
        assert retried["process"] == running["process"]
        later_request = recreated.start(
            {**params, "execution_context_id": "later-context"}, tmp_path
        )
        assert later_request["process"] == running["process"]
        assert later_request["context_id"] is None
        done = await observe(recreated, job_id, {"completed", "failed"})
        assert done["status"] == "completed"
        assert done["returncode"] == 0
        logs = recreated.logs(job_id, 0, 4)
        second = recreated.logs(job_id, logs["next_offset"])
        text = base64.b64decode(logs["data_b64"]) + base64.b64decode(second["data_b64"])
        assert text.count(b"started") == 1
        assert b"finished" in text
        with pytest.raises(ValueError, match="key reused"):
            recreated.start({**params, "argv": ["different"]}, tmp_path)
    finally:
        supervisor.cancel(job_id)
        await observe(supervisor, job_id, {"completed", "failed", "cancelled"})


async def test_job_cancel_returns_request_then_exact_stopped_receipt(tmp_path: Path) -> None:
    supervisor = JobSupervisor(tmp_path / "jobs")
    started = await asyncio.to_thread(
        supervisor.start,
        {
            "argv": [sys.executable, "-c", "import time; time.sleep(60)"],
            "idempotency_key": "cancel",
        },
        tmp_path,
    )
    job_id = started["job_id"]
    try:
        running = await observe(supervisor, job_id, {"running"})
        requested = supervisor.cancel(job_id)
        assert requested["cancel_requested"] is True
        assert requested["status"] == "running"
        stopped = await observe(supervisor, job_id, {"cancelled", "failed", "unknown"})
        assert stopped["status"] == "cancelled"
        assert same_process(running["process"]) is None
        assert supervisor.cancel(job_id)["status"] == "cancelled"
    finally:
        supervisor.cancel(job_id)
        await observe(supervisor, job_id, {"cancelled", "failed", "completed"})


@pytest.mark.parametrize("cancel", [False, True])
async def test_job_tracks_children_after_launcher_exits(tmp_path: Path, cancel: bool) -> None:
    supervisor = JobSupervisor(tmp_path / "jobs")
    child = "import time; print('child started', flush=True); time.sleep(4); print('child finished', flush=True)"
    launcher = "import subprocess, sys; p = subprocess.Popen([sys.executable, '-u', '-c', sys.argv[1]]); print('launched', p.pid, flush=True)"
    started = await asyncio.to_thread(
        supervisor.start,
        {"argv": [sys.executable, "-u", "-c", launcher, child], "idempotency_key": "descendant"},
        tmp_path,
    )
    job_id = started["job_id"]
    try:
        deadline = asyncio.get_running_loop().time() + 15
        while asyncio.get_running_loop().time() < deadline:
            state = supervisor.status(job_id)
            if state.get("parent_returncode") == 0 and state["status"] == "running":
                break
            await asyncio.sleep(0.1)
        else:
            raise AssertionError(f"Child was not retained after its launcher exited: {state}")
        assert state["members"]
        assert any(same_process(value) for value in state["members"])
        assert state["resources"]["rss_bytes"] > 0
        if cancel:
            supervisor.cancel(job_id)
        done = await observe(supervisor, job_id, {"completed", "failed", "cancelled", "unknown"})
        assert done["status"] == ("cancelled" if cancel else "completed")
        assert not any(same_process(value) for value in state["members"])
        if not cancel:
            assert b"child finished" in base64.b64decode(supervisor.logs(job_id)["data_b64"])
    finally:
        supervisor.cancel(job_id)
        await observe(supervisor, job_id, {"completed", "failed", "cancelled", "unknown"})


def test_lost_worker_is_unknown_and_pid_reuse_is_not_a_live_job(tmp_path: Path) -> None:
    supervisor = JobSupervisor(tmp_path / "jobs")
    job_id = "a" * 32
    path = tmp_path / "jobs" / job_id
    path.mkdir(parents=True)
    write_state(path / "job.json", {"job_id": job_id, "created_at": 1, "fingerprint": "unchanged"})
    write_state(
        path / "state.json",
        {
            "status": "running",
            "updated_at": 1,
            "process": {"pid": 0, "created_at": 1},
            "worker": {"pid": 0, "created_at": 1},
        },
    )
    assert supervisor.status(job_id)["status"] == "unknown"
    assert not supervisor.status(job_id)["process_alive"]
    with pytest.raises(ValueError, match="invalid Job id"):
        supervisor.status("../outside")


def test_cancel_recovers_exact_process_after_worker_loss(tmp_path: Path) -> None:
    supervisor = JobSupervisor(tmp_path / "jobs")
    job_id = "b" * 32
    path = supervisor.directory / job_id
    path.mkdir(parents=True)
    process = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
    try:
        identity = process_identity(process.pid)
        write_state(
            path / "job.json", {"job_id": job_id, "created_at": 1, "fingerprint": "unchanged"}
        )
        write_state(
            path / "state.json",
            {
                "status": "running",
                "updated_at": 1,
                "worker": {"pid": 0, "created_at": 1},
                "process": identity,
            },
        )
        assert supervisor.status(job_id)["status"] == "unknown"
        assert supervisor.cancel(job_id)["status"] == "cancelled"
        assert same_process(identity) is None
    finally:
        if process.poll() is None:
            process.kill()
        process.wait()


def test_job_pages_bound_command_previews_and_revocation_visits_every_job(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    supervisor = JobSupervisor(tmp_path / "jobs")
    for number in range(205):
        job_id = f"{number:032x}"
        path = supervisor.directory / job_id
        path.mkdir(parents=True)
        write_state(
            path / "job.json", {"job_id": job_id, "created_at": 1, "argv": ["long argument " * 300]}
        )
        write_state(path / "state.json", {"status": "unknown"})
    first = supervisor.list()
    assert len(first["jobs"]) == 200
    assert first["has_more"] and first["next_offset"] == 200
    assert first["jobs"][0]["argv_truncated"]
    assert sum(map(len, first["jobs"][0]["argv"])) == 2048
    second = supervisor.list(first["next_offset"])
    assert len(second["jobs"]) == 5 and not second["has_more"]
    visited: list[str] = []
    monkeypatch.setattr(supervisor, "cancel", visited.append)
    supervisor.cancel_active()
    assert len(set(visited)) == 205


def test_recovery_cancel_confirms_overlapping_parent_and_child_trees(tmp_path: Path) -> None:
    supervisor = JobSupervisor(tmp_path / "jobs")
    path = supervisor.directory / ("d" * 32)
    path.mkdir(parents=True)
    marker = tmp_path / "child.pid"
    launcher = "import subprocess,sys,time,pathlib; p=subprocess.Popen([sys.executable,'-c','import time;time.sleep(60)']); pathlib.Path(sys.argv[1]).write_text(str(p.pid));time.sleep(60)"
    process = subprocess.Popen([sys.executable, "-c", launcher, str(marker)])
    identities = []
    try:
        deadline = time.monotonic() + 10
        while not marker.exists() and time.monotonic() < deadline:
            time.sleep(0.05)
        identities = [process_identity(process.pid), process_identity(int(marker.read_text()))]
        write_state(
            path / "job.json", {"job_id": "d" * 32, "created_at": 1, "fingerprint": "unchanged"}
        )
        write_state(
            path / "state.json",
            {
                "status": "running",
                "updated_at": 1,
                "worker": {"pid": 0, "created_at": 1},
                "process": identities[0],
                "members": identities,
                "member_count": 2,
            },
        )
        assert supervisor.cancel("d" * 32)["status"] == "cancelled"
        assert not any(same_process(identity) for identity in identities)
    finally:
        from octop.infra.devices.jobs import stop_process_tree

        for identity in identities:
            stop_process_tree(identity)
        if process.poll() is None:
            process.kill()
        process.wait()


@pytest.mark.parametrize(
    ("member_states", "worker_state", "member_count", "expected"),
    [
        (["live", "inaccessible"], "absent", 2, "unknown"),
        (["live", "absent"], "absent", 2, "cancelled"),
        (["live", "reused"], "absent", 2, "cancelled"),
        (["absent", "reused"], "absent", 2, "cancelled"),
        (["inaccessible", "inaccessible"], "absent", 2, "unknown"),
        (["live", "absent"], "inaccessible", 2, "unknown"),
        (["live", "absent"], "absent", 3, "unknown"),
    ],
)
def test_recovery_cancel_requires_receipts_for_every_recorded_identity(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    member_states: list[str],
    worker_state: str,
    member_count: int,
    expected: str,
) -> None:
    from octop.infra.devices import jobs

    supervisor = JobSupervisor(tmp_path / "jobs")
    job_id = "e" * 32
    path = supervisor.directory / job_id
    path.mkdir(parents=True)
    identities = [{"pid": index + 100, "created_at": 1} for index in range(2)]
    worker = {"pid": 200, "created_at": 1}
    states = {
        identity["pid"]: state for identity, state in zip(identities, member_states, strict=True)
    }
    states[worker["pid"]] = worker_state

    class Process:
        def __init__(self, pid: int) -> None:
            self.pid = pid
            if states[pid] == "absent":
                raise psutil.NoSuchProcess(pid)

        def create_time(self) -> float:
            if states[self.pid] == "inaccessible":
                raise psutil.AccessDenied(self.pid)
            return 2 if states[self.pid] == "reused" else 1

        def is_running(self) -> bool:
            return True

        def status(self) -> str:
            return psutil.STATUS_RUNNING

    stopped: list[int] = []

    def stop(identity: dict[str, Any] | None) -> bool:
        assert identity is not None
        if states[identity["pid"]] != "live":
            return False
        stopped.append(identity["pid"])
        states[identity["pid"]] = "absent"
        return True

    checked: list[int] = []
    confirm = jobs.confirmed_stopped

    def confirm_recorded(identity: dict[str, Any] | None) -> bool:
        assert identity is not None
        checked.append(identity["pid"])
        return confirm(identity)

    write_state(path / "job.json", {"job_id": job_id, "created_at": 1})
    write_state(
        path / "state.json",
        {
            "status": "unknown",
            "worker": worker,
            "process": identities[0],
            "members": identities,
            "member_count": member_count,
        },
    )
    monkeypatch.setattr(supervisor, "status", lambda _: jobs.read_state(path / "state.json"))
    monkeypatch.setattr(jobs.psutil, "Process", Process)
    monkeypatch.setattr(jobs, "stop_process_tree", stop)
    monkeypatch.setattr(jobs, "confirmed_stopped", confirm_recorded)
    receipt = supervisor.cancel(job_id)
    assert receipt["status"] == expected
    assert receipt["cancel_requested"]
    assert set(checked) == {100, 101, 200}
    assert stopped == [
        identity["pid"]
        for identity, state in zip(identities, member_states, strict=True)
        if state == "live"
    ]
