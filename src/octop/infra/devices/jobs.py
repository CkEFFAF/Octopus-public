"""Durable Jobs whose worker process is independent of the device connection."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import re
import signal
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any

import psutil

from octop.infra.devices.state_io import retry_file_lock

LOG_LIMIT = 64 * 1024 * 1024
LOG_PAGE = 64 * 1024
TERMINAL_STATES = frozenset({"completed", "failed", "cancelled", "unknown"})
_WORKERS: dict[str, subprocess.Popen[Any]] = {}


def write_state(path: Path, data: dict[str, Any]) -> None:
    fd, temporary = tempfile.mkstemp(prefix=".job-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump(data, stream, ensure_ascii=False)
            stream.flush()
            os.fsync(stream.fileno())
        retry_file_lock(lambda: os.replace(temporary, path))
    finally:
        Path(temporary).unlink(missing_ok=True)


def read_state(path: Path) -> dict[str, Any]:
    try:
        return json.loads(retry_file_lock(lambda: path.read_text(encoding="utf-8")))  # type: ignore[no-any-return]
    except FileNotFoundError:
        return {}


def same_process(identity: dict[str, Any] | None) -> psutil.Process | None:
    if (
        not identity
        or type(identity.get("pid")) is not int
        or not isinstance(identity.get("created_at"), (int, float))
    ):
        return None
    try:
        process = psutil.Process(identity["pid"])
        if (
            process.create_time() == identity["created_at"]
            and process.is_running()
            and process.status() != psutil.STATUS_ZOMBIE
        ):
            return process
    except (psutil.Error, KeyError):
        pass
    return None


def process_identity(pid: int) -> dict[str, Any]:
    try:
        created = psutil.Process(pid).create_time()
    except psutil.NoSuchProcess:
        created = None
    return {"pid": pid, "created_at": created}


def confirmed_stopped(identity: dict[str, Any] | None) -> bool:
    """Distinguish a stopped/reused PID from an inaccessible process identity."""
    if (
        not identity
        or type(identity.get("pid")) is not int
        or not isinstance(identity.get("created_at"), (int, float))
    ):
        return False
    try:
        process = psutil.Process(identity["pid"])
        return (
            process.create_time() != identity["created_at"]
            or not process.is_running()
            or process.status() == psutil.STATUS_ZOMBIE
        )
    except psutil.NoSuchProcess:
        return True
    except psutil.Error:
        return False


def stop_process_tree(identity: dict[str, Any] | None) -> bool:
    """Stop only the recorded process instance and confirm all found children."""
    process = same_process(identity)
    if process is None:
        return False
    try:
        children = process.children(recursive=True)
        if os.name == "posix" and os.getpgid(process.pid) == process.pid:  # type: ignore[attr-defined, unused-ignore]
            os.killpg(process.pid, signal.SIGTERM)  # type: ignore[attr-defined, unused-ignore]
        else:
            for child in [*reversed(children), process]:
                with contextlib.suppress(psutil.NoSuchProcess):
                    child.terminate()
        _, alive = psutil.wait_procs([*children, process], timeout=5)
        for child in alive:
            with contextlib.suppress(psutil.NoSuchProcess):
                child.kill()
        _, alive = psutil.wait_procs(alive, timeout=2)
        return not alive
    except (psutil.Error, OSError):
        return False


class JobSupervisor:
    def __init__(self, directory: Path) -> None:
        self.directory = directory

    def _path(self, job_id: str) -> Path:
        if not re.fullmatch(r"[0-9a-f]{32}", job_id):
            raise ValueError("invalid Job id")
        path = self.directory / job_id
        if not (path / "job.json").is_file():
            raise ValueError("Job unavailable")
        return path

    def start(self, params: dict[str, Any], cwd: Path) -> dict[str, Any]:
        key = params.get("idempotency_key")
        argv = params.get("argv")
        if not isinstance(key, str) or not key or len(key) > 200:
            raise ValueError("Job requires an idempotency key")
        if (
            not isinstance(argv, list)
            or not argv
            or len(argv) > 256
            or any(not isinstance(arg, str) or "\x00" in arg or len(arg) > 32768 for arg in argv)
            or not argv[0]
        ):
            raise ValueError("Job argv must be a nonempty list of strings")
        job_id = hashlib.sha256(key.encode()).hexdigest()[:32]
        payload = {
            "argv": argv,
            "cwd": str(cwd),
            "context_id": params.get("execution_context_id"),
            "policy_revision": params.get("policy_revision"),
            "grant_version": params.get("grant_version"),
        }
        # A retry from a later request still refers to the originally accepted
        # Job. Preserve its origin context, but compare execution parameters.
        fingerprint = hashlib.sha256(
            json.dumps(
                {k: v for k, v in payload.items() if k != "context_id"}, sort_keys=True
            ).encode()
        ).hexdigest()
        path = self.directory / job_id
        self.directory.mkdir(parents=True, exist_ok=True)
        try:
            path.mkdir()
        except FileExistsError:
            if not (path / "job.json").is_file():
                raise ValueError(
                    "Job submission is incomplete; retain its key and inspect before retrying"
                ) from None
            if read_state(path / "job.json")["fingerprint"] != fingerprint:
                raise ValueError("Job key reused with different execution parameters") from None
            return self.status(job_id)
        if os.name == "posix":
            path.chmod(0o700)
        manifest = {
            **payload,
            "job_id": job_id,
            "fingerprint": fingerprint,
            "created_at": time.time(),
        }
        # Publish a complete manifest so concurrent status/list readers can
        # never observe a partially written JSON document.
        write_state(path / "job.json", manifest)
        write_state(path / "state.json", {"status": "queued", "updated_at": time.time()})
        env = dict(os.environ)
        package_root = str(Path(__file__).resolve().parents[3])
        env["PYTHONPATH"] = os.pathsep.join([package_root, *filter(None, [env.get("PYTHONPATH")])])
        spawn: dict[str, Any] = {
            "stdin": subprocess.DEVNULL,
            "stdout": subprocess.DEVNULL,
            "stderr": subprocess.DEVNULL,
            "env": env,
            "close_fds": True,
        }
        if os.name == "nt":
            spawn["creationflags"] = (
                subprocess.DETACHED_PROCESS  # type: ignore[attr-defined, unused-ignore]
                | subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined, unused-ignore]
            )
        else:
            spawn["start_new_session"] = True
        try:
            _WORKERS[job_id] = subprocess.Popen(
                [sys.executable, "-m", "octop.infra.devices.job_worker", str(path)], **spawn
            )
        except OSError:
            write_state(
                path / "state.json",
                {"status": "failed", "reason": "worker launch failed", "updated_at": time.time()},
            )
            raise
        # A durable accepted Job is not a completed experiment.
        return self.status(job_id)

    def status(self, job_id: str) -> dict[str, Any]:
        for key, background_worker in list(_WORKERS.items()):
            if background_worker.poll() is not None:
                _WORKERS.pop(key, None)
        path = self._path(job_id)
        manifest = read_state(path / "job.json")
        state = read_state(path / "state.json")
        child = same_process(state.get("process"))
        members = {
            process.pid: process
            for value in state.get("members", [])
            if (process := same_process(value)) is not None
        }
        if child:
            members[child.pid] = child
        worker = same_process(state.get("worker"))
        if (
            state.get("status") not in TERMINAL_STATES
            and not worker
            and time.time() - state.get("updated_at", manifest["created_at"]) > 15
        ):
            # Never infer completion from a lost worker, or relaunch its command.
            state = {
                **state,
                "status": "unknown",
                "reason": "worker receipt unavailable",
                "process_alive": bool(members),
            }
        resources = None
        if members:
            from octop.infra.devices.resources import gpu_processes

            rss, cpu = 0, 0.0
            for process in members.values():
                with contextlib.suppress(psutil.Error):
                    rss += process.memory_info().rss
                    cpu += sum(process.cpu_times()[:2])
            resources = {"rss_bytes": rss, "cpu_seconds": cpu, "gpu": gpu_processes(set(members))}
        return {
            **{k: v for k, v in manifest.items() if k != "fingerprint"},
            **state,
            "resources": resources,
            "observed_at": time.time(),
        }

    def _ids(self) -> list[str]:
        if not self.directory.exists():
            return []
        paths = [
            p
            for p in self.directory.iterdir()
            if re.fullmatch(r"[0-9a-f]{32}", p.name) and (p / "job.json").is_file()
        ]
        return [
            p.name
            for p in sorted(paths, key=lambda p: (p / "job.json").stat().st_mtime_ns, reverse=True)
        ]

    def list(self, offset: int = 0, limit: int = 200) -> dict[str, Any]:
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 200:
            raise ValueError("invalid Job listing range")
        ids = self._ids()
        jobs = []
        for job_id in ids[offset : offset + limit]:
            job = self.status(job_id)
            budget, preview = 2048, []
            for arg in job.get("argv", []):
                if budget <= 0:
                    break
                preview.append(arg[:budget])
                budget -= len(preview[-1])
            jobs.append({**job, "argv": preview, "argv_truncated": preview != job.get("argv", [])})
        more = offset + len(jobs) < len(ids)
        return {"jobs": jobs, "has_more": more, "next_offset": offset + len(jobs) if more else None}

    def cancel_active(self) -> None:
        """Apply revocation to every Job, independently of UI page limits."""
        for job_id in self._ids():
            if self.status(job_id)["status"] in {"queued", "running", "unknown"}:
                self.cancel(job_id)

    def logs(self, job_id: str, offset: int = 0, length: int = LOG_PAGE) -> dict[str, Any]:
        if (
            type(offset) is not int
            or offset < 0
            or type(length) is not int
            or not 1 <= length <= LOG_PAGE
        ):
            raise ValueError("invalid Job log range")
        path = self._path(job_id) / "output.log"
        data = b""
        if path.exists():
            with path.open("rb") as stream:
                stream.seek(offset)
                data = stream.read(length)
        state = self.status(job_id)
        return {
            "job_id": job_id,
            "offset": offset,
            "next_offset": offset + len(data),
            "data_b64": base64.b64encode(data).decode(),
            "status": state["status"],
            "truncated": state.get("log_truncated", False),
        }

    def cancel(self, job_id: str) -> dict[str, Any]:
        path = self._path(job_id)
        state = self.status(job_id)
        if state["status"] in {"completed", "failed", "cancelled"}:
            return state
        (path / "cancel.request").touch(exist_ok=True)
        identities = list(state.get("members") or [state.get("process")])
        coverage_complete = state.get("member_count", len(identities)) <= len(identities)
        if state.get("process") and state["process"] not in identities:
            identities.append(state["process"])
        if not same_process(state.get("worker")):
            receipts = [
                confirmed_stopped(value) or (stop_process_tree(value) and confirmed_stopped(value))
                for value in identities
            ]
            worker_stopped = state.get("worker") is None or confirmed_stopped(state["worker"])
            stopped = all(receipts) and coverage_complete and worker_stopped
            write_state(
                path / "state.json",
                {
                    **{k: v for k, v in state.items() if k not in {"resources", "observed_at"}},
                    "status": "cancelled" if stopped else "unknown",
                    "cancel_requested": True,
                    "reason": "recovered cancellation after worker loss"
                    if stopped
                    else "cancellation receipt unavailable",
                    "updated_at": time.time(),
                },
            )
            return self.status(job_id)
        return {**state, "cancel_requested": True}
