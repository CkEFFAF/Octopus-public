"""Device expert command boundaries, private config and interrupted sends."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest
from click.testing import CliRunner

from octop.cli.main import cli
from octop.infra.devices.expert_client import (
    ExpertClient,
    ExpertClientError,
    ExpertConfig,
    expert_server_url,
)


@pytest.mark.parametrize(
    "endpoint",
    [
        "http://remote.test",
        "https://user:secret@remote.test",
        "https://remote.test?token=secret",
        "https://remote.test/#fragment",
        "https://remote.test\n",
        "https://remote.test\\other",
    ],
)
def test_expert_rejects_unsafe_endpoints(endpoint):
    with pytest.raises(ExpertClientError, match="invalid_server"):
        expert_server_url(endpoint)


def test_token_configuration_is_private_hidden_and_reuses_controller(tmp_path, monkeypatch):
    monkeypatch.setattr(
        "octop.cli.device_expert_cmd.DeviceNetwork.controllers",
        lambda self: [
            {"id": "default", "server_url": "https://cloud.test", "status": "configured"}
        ],
    )
    monkeypatch.setattr(
        ExpertClient,
        "identity",
        lambda self: {"credential_id": "key-1", "experts": [], "scopes": ["tasks.read"]},
    )
    result = CliRunner().invoke(
        cli,
        ["device", "expert", "--state", str(tmp_path), "configure"],
        input="oaa_private-value\n",
    )
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["server_url"] == "https://cloud.test"
    assert "oaa_private-value" not in result.output
    config = ExpertConfig(tmp_path)
    assert config.load()["token"] == "oaa_private-value"
    assert "token" not in config.public()
    if os.name != "nt":
        assert config.path.stat().st_mode & 0o777 == 0o600
        assert config.path.parent.stat().st_mode & 0o777 == 0o700

    def rejected(self):
        raise ExpertClientError("auth_failed", status=401)

    monkeypatch.setattr(ExpertClient, "identity", rejected)
    with pytest.raises(ExpertClientError):
        config.configure("https://other.test", "oaa_rejected")
    assert config.load()["token"] == "oaa_private-value"
    assert config.public()["server_url"] == "https://cloud.test"


@pytest.mark.parametrize("committed", [False, True])
def test_lost_create_response_recovers_without_reposting(tmp_path, monkeypatch, committed):
    client = ExpertClient(
        "https://cloud.test", "oaa_test", journal=tmp_path / "commands", credential_id="key-1"
    )
    dispatched = []
    task = {
        "task_id": "task-1",
        "agent_id": "expert-1",
        "origin_thread_id": "thread-1",
        "status": "completed",
        "progress": {"output_text": "回复"},
    }

    def request(method, path, body=None):
        if method == "GET" and path.startswith("/api/work-items?"):
            return {"items": [task] if dispatched and committed else []}
        if method == "GET":
            return task
        if path.endswith("/threads"):
            return {"thread_id": "thread-1"}
        assert list((tmp_path / "commands").glob("*.json"))
        dispatched.append(body)
        raise ExpertClientError("request_unconfirmed")

    monkeypatch.setattr(client, "request", request)
    with pytest.raises(ExpertClientError) as error:
        client.send("问题", expert_id="expert-1", command_id="command-1", wait=0)
    assert error.value.command_id == "command-1"
    if committed:
        assert (
            client.send("问题", expert_id="expert-1", command_id="command-1", wait=0)["task_id"]
            == "task-1"
        )
    else:
        with pytest.raises(ExpertClientError, match="request_unconfirmed"):
            client.send("问题", expert_id="expert-1", command_id="command-1", wait=0)
    assert len(dispatched) == 1
    assert all("oaa_test" not in p.read_text() for p in (tmp_path / "commands").glob("*.json"))


def test_unconfirmed_input_never_becomes_a_new_task(tmp_path, monkeypatch):
    client = ExpertClient(
        "https://cloud.test", "oaa_test", journal=tmp_path / "commands", credential_id="key-1"
    )
    calls = []
    task = {
        "task_id": "task-1",
        "agent_id": "expert-1",
        "origin_thread_id": "thread-1",
        "status": "running",
        "progress": {},
    }

    def request(method, path, body=None):
        calls.append((method, path))
        if method == "GET" and path.startswith("/api/work-items?"):
            return {"items": []}
        if method == "GET" and "/inputs?" in path:
            return {"receipt": None}
        if method == "GET":
            return task
        assert path.endswith("/inputs")
        task["status"] = "completed"
        raise ExpertClientError("request_unconfirmed")

    monkeypatch.setattr(client, "request", request)
    for _ in range(2):
        with pytest.raises(ExpertClientError, match="request_unconfirmed"):
            client.send("补充", task_id="task-1", command_id="input-1", wait=0)
    assert len([item for item in calls if item[0] == "POST"]) == 1


def test_redirect_never_forwards_expert_token():
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            self.send_response(302)
            self.send_header("Location", "/redirect-target")
            self.end_headers()

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        client = ExpertClient(f"http://127.0.0.1:{server.server_port}", "oaa_secret")
        with pytest.raises(ExpertClientError) as error:
            client.identity()
        assert error.value.status == 302
        assert "oaa_secret" not in json.dumps(error.value.payload())
        assert seen == ["/api/auth/agent-access-keys/identity"]
    finally:
        server.shutdown()
        thread.join(timeout=5)
        server.server_close()


def test_oversized_token_file_is_rejected_before_connecting(tmp_path, monkeypatch):
    token = tmp_path / "token"
    token.write_bytes(b"oaa_" + b"x" * 5000)

    def unexpected(self):
        pytest.fail("oversized token must not reach the server")

    monkeypatch.setattr(ExpertClient, "identity", unexpected)
    result = CliRunner().invoke(
        cli,
        [
            "device",
            "expert",
            "--state",
            str(tmp_path),
            "configure",
            "--server",
            "https://cloud.test",
            "--token-file",
            str(token),
        ],
    )
    assert result.exit_code == 1
    assert json.loads(result.stderr)["error"] == "invalid_token"
    assert not ExpertConfig(tmp_path).path.exists()


@pytest.mark.parametrize("cursor", ["older-page", None])
def test_complete_reply_reads_older_history_pages_in_order(monkeypatch, cursor):
    client = ExpertClient("https://cloud.test", "oaa_test")
    calls = []

    def request(method, path, body=None):
        calls.append(path)
        if len(calls) == 1:
            return {
                "messages": [{"role": "assistant", "content": "后一段"}],
                "has_more": True,
                "next_cursor": cursor,
            }
        assert ("cursor=older-page" in path) if cursor else ("offset=1" in path)
        return {
            "messages": [{"role": "assistant", "content": "前一段"}],
            "has_more": False,
        }

    monkeypatch.setattr(client, "request", request)
    result = client.result(
        {
            "task_id": "task-1",
            "origin_thread_id": "thread-1",
            "agent_id": "expert-1",
            "worker_thread_id": "worker-1",
            "status": "completed",
            "progress": {},
        }
    )
    assert result["reply"] == "前一段\n后一段"
    assert len(calls) == 2


def test_linux_device_allowlist_can_import_expert_without_server_dependencies(tmp_path):
    root = Path(__file__).resolve().parents[3]
    script = (root / "desktop/portable/package-device-linux.sh").read_text(encoding="utf-8")
    modules = re.search(r"MODULES=\((.*?)\n\)", script, re.S).group(1).split()
    data = re.search(r"DATA_FILES=\((.*?)\)", script, re.S).group(1).split()
    packages = tmp_path / "packages"
    for name in modules + data:
        target = packages / "octop" / name
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(root / "src/octop" / name, target)
    code = """
import importlib.abc, json, sys
class WithoutServer(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname.split('.')[0] in {'httpx', 'acp', 'fastapi', 'pydantic', 'octop_harness', 'langgraph'}:
            raise ImportError('server dependency: ' + fullname)
sys.meta_path.insert(0, WithoutServer())
sys.path.insert(0, sys.argv[1])
from click.testing import CliRunner
from octop.cli.device_cmd import device
result = CliRunner().invoke(device, ['expert', '--state', sys.argv[2], 'config'])
assert result.exit_code == 1, result.output
assert json.loads(result.stderr)['error'] == 'not_configured', result.output
print('standalone expert import passed')
"""
    result = subprocess.run(
        [sys.executable, "-I", "-c", code, str(packages), str(tmp_path / "state")],
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=20,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "standalone expert import passed" in result.stdout
    assert "/expert.sh" in script
    assert "expert.bat" in (root / "desktop/portable/package.sh").read_text(encoding="utf-8")
