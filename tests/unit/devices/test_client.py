from __future__ import annotations

import asyncio
import json
import os
import sys

import pytest
import websockets
from click.testing import CliRunner

from octop.cli.main import cli
from octop.infra.devices.client import DeviceClient, validate_server_url
from octop.infra.devices.executor import DeviceExecutionError, DeviceExecutor


def executor_for(tmp_path):
    root = tmp_path / "shared"
    root.mkdir(exist_ok=True)
    roots = [{"id": "shared", "name": "Shared", "path": str(root), "read": True, "write": True}]
    executor = DeviceExecutor(["files_read", "files_write"], roots, state_dir=tmp_path / "state")
    return executor, root


@pytest.mark.parametrize(
    "url", ["http://example.test", "http://192.168.1.2:8088", "http://[2001:db8::1]"]
)
def test_remote_http_requires_explicit_opt_in(url):
    with pytest.raises(DeviceExecutionError, match="allow-insecure"):
        validate_server_url(url)
    assert validate_server_url(url, allow_insecure=True) == url


@pytest.mark.parametrize(
    "url",
    ["http://localhost:8088", "http://127.0.0.1:8088", "http://[::1]:8088", "https://example.test"],
)
def test_loopback_http_or_trusted_tls_allowed(url):
    assert validate_server_url(url + "/") == url


@pytest.mark.parametrize(
    "url",
    [
        "ftp://host",
        "https://user:password@host",
        "https://host?token=secret",
        "https://host#fragment",
        "https://",
        "http://host:invalid",
    ],
)
def test_rejects_credential_urls_and_non_http(url):
    with pytest.raises(DeviceExecutionError):
        validate_server_url(url, allow_insecure=True)


async def test_enrollment_persists_only_device_identity_and_local_consent(tmp_path, monkeypatch):
    executor, root = executor_for(tmp_path)
    client = DeviceClient(tmp_path / "state")
    requests = []

    def enrollment(url, payload):
        requests.append((url, payload))
        return {"device": {"device_id": "device-one"}, "device_token": "odv_device_only_secret"}

    monkeypatch.setattr("octop.infra.devices.client._enroll_http", enrollment)
    device = await client.enroll("https://controller.test", "pair-once", "My workstation", executor)
    assert device["device_id"] == "device-one"
    assert len(requests) == 1
    payload = requests[0][1]
    assert payload["pairing_code"] == "pair-once"
    assert payload["permissions"] == ["files_read", "files_write"]
    assert "owner_user_id" not in payload
    assert "password" not in payload
    state = json.loads(client.state_path.read_text())
    assert state["device_token"] == "odv_device_only_secret"
    assert state["policy"]["roots"][0]["path"] == str(root)
    assert "pair-once" not in client.state_path.read_text()
    assert "password" not in client.state_path.read_text()
    with pytest.raises(DeviceExecutionError, match="already enrolled"):
        await client.enroll("https://controller.test", "another-code", "Other", executor)
    assert len(requests) == 1
    saved = client.saved_executor()
    assert saved.local_permissions == {"files_read", "files_write"}
    if os.name != "nt":
        assert client.state_dir.stat().st_mode & 0o777 == 0o700
        assert client.state_path.stat().st_mode & 0o777 == 0o600


async def test_failed_enrollment_does_not_create_identity(tmp_path, monkeypatch):
    executor, _ = executor_for(tmp_path)
    client = DeviceClient(tmp_path / "state")
    monkeypatch.setattr(
        "octop.infra.devices.client._enroll_http",
        lambda url, payload: {"device": {}, "device_token": "user-jwt"},
    )
    with pytest.raises(DeviceExecutionError, match="invalid enrollment"):
        await client.enroll("https://controller.test", "code", "Device", executor)
    assert client.load_state() is None


class FakeSocket:
    def __init__(self):
        self.frames = asyncio.Queue()
        self.sent = []
        self.closed = False

    def __aiter__(self):
        return self

    async def __anext__(self):
        frame = await self.frames.get()
        if frame is None:
            raise StopAsyncIteration
        return json.dumps(frame)

    async def send(self, raw):
        self.sent.append(json.loads(raw))

    async def close(self):
        self.closed = True
        await self.frames.put(None)


async def until(predicate):
    for _ in range(200):
        if predicate():
            return
        await asyncio.sleep(0.01)
    assert predicate()


async def test_heartbeat_and_changed_grants_apply_within_capabilities(tmp_path, monkeypatch):
    executor, root = executor_for(tmp_path)
    executor.update_grants(1, ["files_read", "files_write"], list(executor.local_roots.values()))
    (root / "file").write_text("data")
    client = DeviceClient(tmp_path / "state")
    socket = FakeSocket()
    monkeypatch.setattr("octop.infra.devices.client.HEARTBEAT_INTERVAL", 0.02)
    task = asyncio.create_task(client._connected(socket, executor))
    await until(lambda: any(frame["type"] == "heartbeat" for frame in socket.sent))
    await socket.frames.put(
        {
            "type": "heartbeat_ack",
            "grant_version": 2,
            "permissions": ["files_read", "command_exec", "desktop_control"],
            "roots": list(executor.local_roots.values()),
        }
    )
    await until(lambda: executor.grant_version == 2)
    # 0005: remote grants may expand up to capabilities (no longer local-consent ∩).
    assert executor.permissions == {"files_read", "command_exec", "desktop_control"}
    await socket.frames.put(
        {
            "type": "request",
            "id": "denied",
            "action": "files.write_begin",
            "params": {},
            "grant_version": 2,
            "permissions": ["files_write"],
        }
    )
    await until(lambda: any(frame.get("id") == "denied" for frame in socket.sent))
    response = next(frame for frame in socket.sent if frame.get("id") == "denied")
    assert response["ok"] is False
    assert "permission" in response["error"]
    await socket.close()
    await task


async def test_missing_heartbeat_ack_closes_connection(tmp_path, monkeypatch):
    executor, _ = executor_for(tmp_path)
    client = DeviceClient(tmp_path / "state")
    socket = FakeSocket()
    monkeypatch.setattr("octop.infra.devices.client.HEARTBEAT_INTERVAL", 0.01)
    monkeypatch.setattr("octop.infra.devices.client.HEARTBEAT_TIMEOUT", 0.03)
    await asyncio.wait_for(client._connected(socket, executor), 1)
    assert socket.closed


async def test_queued_cancel_never_starts_operation(tmp_path, monkeypatch):
    executor, _ = executor_for(tmp_path)
    executor.update_grants(1, ["files_read", "files_write"], list(executor.local_roots.values()))
    client = DeviceClient(tmp_path / "state")
    socket = FakeSocket()
    executed = []
    original = executor.execute

    async def execute(*args, **kwargs):
        executed.append(args[0])
        return await original(*args, **kwargs)

    monkeypatch.setattr(executor, "execute", execute)
    await socket.frames.put(
        {
            "type": "request",
            "id": "queued",
            "action": "ping",
            "params": {},
            "grant_version": 1,
            "permissions": [],
        }
    )
    await socket.frames.put({"type": "cancel", "id": "queued"})
    await socket.frames.put(None)
    await client._connected(socket, executor)
    assert executed == []


@pytest.mark.parametrize("large_output", [False, True])
async def test_real_outbound_websocket_reconnect_keeps_identity_and_reconciles(
    tmp_path, monkeypatch, caplog, large_output
):
    executor, _ = executor_for(tmp_path)
    if large_output:
        executor = DeviceExecutor(
            ["files_read", "files_write", "command_exec"],
            list(executor.local_roots.values()),
            state_dir=tmp_path / "state",
            command_enabled=True,
        )
    client = DeviceClient(tmp_path / "state")
    hellos, receipts, paths = [], [], []
    twice = asyncio.Event()

    async def controller(socket):
        paths.append(socket.request.path)
        hello = json.loads(await socket.recv())
        hellos.append(hello)
        await socket.send(
            json.dumps(
                {
                    "type": "hello_ack",
                    "protocol": 1,
                    "connection_id": str(len(hellos)),
                    "grant_version": 1,
                    "permissions": sorted(executor.local_permissions),
                    "roots": list(executor.local_roots.values()),
                }
            )
        )
        if len(hellos) == 1:
            await socket.send(
                json.dumps(
                    {
                        "type": "request",
                        "id": "one-request",
                        "action": "command.run" if large_output else "ping",
                        "params": {
                            "root_id": "shared",
                            "argv": [
                                sys.executable,
                                "-c",
                                "import sys; data=chr(0x4e2d).encode('utf-8')*400000; "
                                "sys.stdout.buffer.write(data); sys.stderr.buffer.write(data)",
                            ],
                        }
                        if large_output
                        else {},
                        "grant_version": 1,
                        "permissions": ["command_exec"] if large_output else [],
                    }
                )
            )
            async for raw in socket:
                frame = json.loads(raw)
                if frame.get("type") == "result" and frame.get("id") == "one-request":
                    assert frame["ok"] is True
                    assert len(raw.encode("utf-8")) <= 4 * 1024 * 1024
                    if large_output:
                        assert frame["result"]["stdout"].startswith("中")
                        assert frame["result"]["truncated"] is True
                    await socket.close()
                    return
        else:
            async for raw in socket:
                frame = json.loads(raw)
                if frame.get("type") == "reconcile":
                    assert len(raw.encode("utf-8")) <= 4 * 1024 * 1024
                    receipts.extend(frame["results"])
                    if any(item["id"] == "one-request" for item in receipts):
                        twice.set()
                        await socket.wait_closed()
                        return

    async with websockets.serve(controller, "127.0.0.1", 0, max_size=4 * 1024 * 1024) as server:
        port = server.sockets[0].getsockname()[1]
        monkeypatch.setattr(
            "octop.infra.devices.client._enroll_http",
            lambda url, payload: {
                "device": {"device_id": "stable-id"},
                "device_token": "odv_do_not_log",
            },
        )
        await client.enroll(f"http://127.0.0.1:{port}", "once", "Device", executor)
        caplog.set_level("DEBUG")
        # The test controller also logs frames; disable that independently so
        # this assertion measures the client's private transport logging.
        caplog.set_level("WARNING", logger="websockets.server")
        running = asyncio.create_task(client.run(executor))
        await asyncio.wait_for(twice.wait(), 10)
        await client.stop()
        await asyncio.wait_for(running, 5)
    assert len(hellos) == 2
    assert {hello["device_id"] for hello in hellos} == {"stable-id"}
    assert {hello["token"] for hello in hellos} == {"odv_do_not_log"}
    assert paths == ["/api/devices/connect/ws", "/api/devices/connect/ws"]
    assert receipts[-1]["ok"] is True
    if large_output:
        assert receipts[-1]["result"]["stdout"].startswith("中")
        assert receipts[-1]["result"]["truncated"] is True
    assert "odv_do_not_log" not in caplog.text


def test_cli_device_is_lazy_registered_and_control_requires_view():
    runner = CliRunner()
    assert "device" in runner.invoke(cli, ["--help"]).output
    help_result = runner.invoke(cli, ["device", "connect", "--help"])
    assert help_result.exit_code == 0
    assert "--allow-command" in help_result.output
    result = runner.invoke(cli, ["device", "connect", "--control"])
    assert result.exit_code != 0
    assert "--control requires --desktop" in result.output


def test_state_file_symlink_cannot_disclose_or_overwrite(tmp_path):
    client = DeviceClient(tmp_path / "state")
    target = tmp_path / "private"
    target.write_text("unchanged")
    try:
        client.state_path.symlink_to(target)
    except OSError:
        pytest.skip("symlink creation is not available to this OS user")
    with pytest.raises(DeviceExecutionError, match="symlink"):
        client.load_state()
    assert target.read_text() == "unchanged"


async def test_account_token_enroll_sends_bearer_not_body_owner(tmp_path, monkeypatch):
    """0004: account JWT goes in Authorization; never persisted in device-state."""
    executor, root = executor_for(tmp_path)
    client = DeviceClient(tmp_path / "state")
    requests = []

    def enrollment(url, payload, *, authorization=None):
        requests.append((url, payload, authorization))
        return {"device": {"device_id": "device-account"}, "device_token": "odv_account_secret"}

    monkeypatch.setattr("octop.infra.devices.client._enroll_http", enrollment)
    device = await client.enroll(
        "https://controller.test",
        "",
        "Account PC",
        executor,
        account_token="jwt-from-password-login",
    )
    assert device["device_id"] == "device-account"
    assert len(requests) == 1
    _url, payload, authorization = requests[0]
    assert authorization == "Bearer jwt-from-password-login"
    assert "pairing_code" not in payload
    assert "access_key" not in payload
    assert "owner_user_id" not in payload
    state_text = client.state_path.read_text(encoding="utf-8")
    assert "jwt-from-password-login" not in state_text
    assert "odv_account_secret" in state_text
    fresh = DeviceClient(tmp_path / "state-mixed")
    with pytest.raises(DeviceExecutionError, match="one pairing credential"):
        await fresh.enroll(
            "https://controller.test",
            "pair",
            "Both",
            executor,
            account_token="jwt",
        )
