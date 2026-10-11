from __future__ import annotations

import asyncio
import json
import os

import pytest
import websockets

from octop.infra.devices.client import DeviceClient
from octop.infra.devices.executor import DeviceExecutionError, save_private_json
from octop.infra.devices.network import DeviceNetwork


def enroll_stub(monkeypatch: pytest.MonkeyPatch) -> None:
    def enroll(url, payload):
        suffix = url.rsplit(":", 1)[-1].replace("/", "-")
        return {
            "device": {"device_id": f"device-{suffix}"},
            "device_token": f"odv_private-{suffix}",
        }

    monkeypatch.setattr("octop.infra.devices.client._enroll_http", enroll)


async def test_add_independent_profiles_preserves_legacy_and_redacts_credentials(
    tmp_path, monkeypatch
):
    enroll_stub(monkeypatch)
    network = DeviceNetwork(tmp_path / "state")
    legacy = {
        "server_url": "https://legacy.test",
        "device_id": "legacy-id",
        "device_token": "odv_legacy-private",
        "policy": {"permissions": [], "roots": []},
    }
    save_private_json(network.state_dir / "device.json", legacy)
    before = (network.state_dir / "device.json").read_bytes()
    added = await network.add_controller("https://second.test", "one-use-code", "Linux", [], [])
    child_path = network.state_dir / "controllers" / added["id"] / "device.json"
    child = json.loads(child_path.read_text())
    assert child["device_token"] != legacy["device_token"]
    assert (network.state_dir / "device.json").read_bytes() == before
    assert "one-use-code" not in child_path.read_text()
    metadata = json.dumps(network.controllers())
    assert "odv_" not in metadata
    assert "roots" not in metadata
    assert {item["id"] for item in network.controllers()} == {"default", added["id"]}
    if os.name != "nt":
        assert child_path.stat().st_mode & 0o777 == 0o600


async def test_duplicate_endpoint_does_not_reenroll(tmp_path, monkeypatch):
    enroll_stub(monkeypatch)
    network = DeviceNetwork(tmp_path / "state")
    await network.add_controller("https://SECOND.test:443/path/", "once", "Linux", [], [])
    with pytest.raises(DeviceExecutionError, match="already configured"):
        await network.add_controller("https://second.test/path", "twice", "Linux", [], [])
    assert len(network.controllers()) == 1


async def test_failed_enrollment_is_not_listed_and_existing_profile_unchanged(
    tmp_path, monkeypatch
):
    enroll_stub(monkeypatch)
    network = DeviceNetwork(tmp_path / "state")
    await network.add_controller("https://first.test", "once", "Linux", [], [])
    before = network.catalog_path.read_bytes()
    monkeypatch.setattr(
        "octop.infra.devices.client._enroll_http",
        lambda url, payload: {"device": {}, "device_token": "wrong-kind"},
    )
    with pytest.raises(DeviceExecutionError, match="invalid enrollment"):
        await network.add_controller("https://second.test", "twice", "Linux", [], [])
    assert network.catalog_path.read_bytes() == before


@pytest.mark.parametrize("value", [{}, {"version": 1, "controllers": [{"id": "../escape"}]}])
def test_catalog_tampering_never_uses_external_state(tmp_path, value):
    network = DeviceNetwork(tmp_path / "state")
    save_private_json(network.catalog_path, value)
    with pytest.raises(DeviceExecutionError, match="invalid device network catalog"):
        network.controllers()


async def test_network_lock_excludes_run_and_configuration_then_releases(tmp_path, monkeypatch):
    enroll_stub(monkeypatch)
    network = DeviceNetwork(tmp_path / "state")
    other = DeviceNetwork(network.state_dir)
    with network.locked():
        with pytest.raises(DeviceExecutionError, match="already running"), other.locked():
            pass
        with pytest.raises(DeviceExecutionError, match="stop it"):
            await other.add_controller("https://first.test", "once", "Linux", [], [])
    with other.locked():
        pass


async def test_remove_local_trust_preserves_saved_identity_and_journal(tmp_path, monkeypatch):
    enroll_stub(monkeypatch)
    network = DeviceNetwork(tmp_path / "state")
    profile = await network.add_controller("https://first.test", "once", "Linux", [], [])
    directory = network.state_dir / "controllers" / profile["id"]
    save_private_json(directory / "operations.json", {"receipt": {"state": "completed"}})
    before = (directory / "device.json").read_bytes()
    network.remove_controller(profile["id"])
    assert network.controllers() == []
    assert (directory / "device.json").read_bytes() == before
    assert (directory / "operations.json").exists()
    with pytest.raises(DeviceExecutionError, match="invalid controller identifier"):
        network.remove_controller("../../outside")


async def test_invalid_profile_cannot_stop_other_executor_and_shutdown_closes_it(
    tmp_path, monkeypatch
):
    enroll_stub(monkeypatch)
    network = DeviceNetwork(tmp_path / "state")
    good = await network.add_controller("https://good.test", "once", "Linux", [], [])
    bad = await network.add_controller("https://bad.test", "twice", "Linux", [], [])
    (network.state_dir / "controllers" / bad["id"] / "device.json").write_text("broken")
    entered = asyncio.Event()
    closed = asyncio.Event()
    executors = []

    async def run(client, executor):
        executors.append(executor)
        entered.set()
        try:
            await client._stop.wait()
        finally:
            closed.set()

    monkeypatch.setattr(DeviceClient, "run", run)
    statuses = []
    running = asyncio.create_task(
        network.run(lambda profile, status: statuses.append((profile, status)))
    )
    await asyncio.wait_for(entered.wait(), 2)
    assert not running.done()
    assert (bad["id"], "attention required") in statuses
    assert (good["id"], "connecting") in statuses
    await network.stop()
    await asyncio.wait_for(running, 2)
    assert closed.is_set()
    assert len(executors) == 1
    assert network._clients == {}
    with DeviceNetwork(network.state_dir).locked():
        pass


async def test_rejected_manager_is_isolated_and_cancellation_releases_every_client(
    tmp_path, monkeypatch
):
    enroll_stub(monkeypatch)
    network = DeviceNetwork(tmp_path / "state")
    good = await network.add_controller("https://good.test", "once", "Linux", [], [])
    bad = await network.add_controller("https://bad.test", "twice", "Linux", [], [])
    active = asyncio.Event()
    rejected = asyncio.Event()
    exited = asyncio.Event()
    executors = {}

    async def run(client, executor):
        host = client.load_state()["server_url"]
        executors[host] = executor
        if host == "https://bad.test":
            rejected.set()
            raise DeviceExecutionError("authentication rejected; private secret must not appear")
        active.set()
        try:
            await client._stop.wait()
        finally:
            exited.set()

    monkeypatch.setattr(DeviceClient, "run", run)
    statuses = []
    running = asyncio.create_task(
        network.run(lambda profile, status: statuses.append((profile, status)))
    )
    await asyncio.wait_for(asyncio.gather(active.wait(), rejected.wait()), 2)
    assert not running.done()
    assert (bad["id"], "attention required") in statuses
    assert (good["id"], "connecting") in statuses
    assert "private secret" not in json.dumps(statuses)
    assert executors["https://good.test"] is not executors["https://bad.test"]
    assert executors["https://good.test"].state_dir != executors["https://bad.test"].state_dir
    running.cancel()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert exited.is_set()
    assert network._clients == {}
    with DeviceNetwork(network.state_dir).locked():
        pass


async def test_two_real_managers_survive_one_disconnect_and_reconnect_same_identity(
    tmp_path, monkeypatch
):
    enroll_stub(monkeypatch)
    network = DeviceNetwork(tmp_path / "state")
    seen = {"a": [], "b": []}
    sockets = {}
    connected = {"a": asyncio.Event(), "b": asyncio.Event()}
    reconnected = asyncio.Event()
    file_read = asyncio.Event()
    shared = tmp_path / "share"
    shared.mkdir()
    (shared / "proof.txt").write_text("still available")
    roots = [{"id": "root", "name": "Shared", "path": str(shared), "read": True, "write": False}]

    def handler(name):
        async def accept(socket):
            hello = json.loads(await socket.recv())
            seen[name].append(hello)
            sockets[name] = socket
            await socket.send(
                json.dumps(
                    {
                        "type": "hello_ack",
                        "protocol": 1,
                        "grant_version": 1,
                        "permissions": ["files_read"],
                        "roots": roots,
                    }
                )
            )
            connected[name].set()
            if name == "a" and len(seen[name]) == 2:
                reconnected.set()
            async for raw in socket:
                frame = json.loads(raw)
                if (
                    name == "b"
                    and frame.get("type") == "result"
                    and frame.get("id") == "read-after-a-offline"
                ):
                    assert frame["ok"] is True
                    assert frame["result"]["entries"][0]["name"] == "proof.txt"
                    file_read.set()

        return accept

    async with (
        websockets.serve(handler("a"), "127.0.0.1", 0) as host_a,
        websockets.serve(handler("b"), "127.0.0.1", 0) as host_b,
    ):
        port_a = host_a.sockets[0].getsockname()[1]
        port_b = host_b.sockets[0].getsockname()[1]
        await network.add_controller(
            f"http://127.0.0.1:{port_a}", "a", "Device", ["files_read"], roots
        )
        await network.add_controller(
            f"http://127.0.0.1:{port_b}", "b", "Device", ["files_read"], roots
        )
        running = asyncio.create_task(network.run())
        try:
            await asyncio.wait_for(
                asyncio.gather(*(event.wait() for event in connected.values())), 5
            )
            await sockets["a"].close()
            await sockets["b"].send(
                json.dumps(
                    {
                        "type": "request",
                        "id": "read-after-a-offline",
                        "action": "files.list",
                        "params": {"root_id": "root", "path": ""},
                        "grant_version": 1,
                        "permissions": ["files_read"],
                    }
                )
            )
            await asyncio.wait_for(file_read.wait(), 5)
            await asyncio.wait_for(reconnected.wait(), 8)
            assert len(seen["b"]) == 1
            assert seen["a"][0]["device_id"] == seen["a"][1]["device_id"]
            assert seen["a"][0]["token"] == seen["a"][1]["token"]
            assert len({client.state_dir for client in network._clients.values()}) == 2
        finally:
            await network.stop()
            await asyncio.wait_for(running, 5)
