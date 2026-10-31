"""tests/integration/test_acp_api.py — ACP runner configuration API."""

from __future__ import annotations

import pytest


@pytest.fixture
async def env(env_acp_agent):
    yield env_acp_agent


async def test_owned_device_runner_override_and_reset(env):
    c, srv, auth, agent = env
    service = srv.app_runtime.devices
    owner = srv.app_runtime.agent_registry.get_row(agent).user_id
    device = service.enroll(
        pairing_code=service.pairing(owner)["pairing_code"],
        name="test",
        platform="windows",
        capabilities=[],
        permissions=[],
        roots=[],
    )["device"]["device_id"]
    endpoint = f"/api/devices/{device}/acp"
    response = await c.get(endpoint, headers=auth)
    assert response.status_code == 200
    runner = {
        **response.json()["runners"]["opencode"],
        "command": "device-command",
        "enabled": True,
    }
    response = await c.put(endpoint + "/opencode", headers=auth, json=runner)
    assert response.status_code == 200
    assert response.json()["overrides"] == ["opencode"]
    assert (await c.get("/api/acp/opencode", headers=auth)).json()["command"] == "opencode"
    assert (
        await c.put(endpoint + "/opencode", headers=auth, json={**runner, "env": {"KEY": "secret"}})
    ).status_code == 400
    assert (await c.get("/api/devices/foreign-device/acp", headers=auth)).status_code in {403, 404}
    response = await c.delete(endpoint + "/opencode", headers=auth)
    assert response.json()["overrides"] == []


async def test_acp_config_round_trip(env) -> None:
    c, _srv, auth, agent_id = env

    r = await c.get(f"/api/agents/{agent_id}/acp", headers=auth)
    assert r.status_code == 200
    body = r.json()
    assert body["tool_enabled"] is False
    assert "opencode" in body["runners"]

    payload = {
        "tool_enabled": True,
        "runners": {
            "opencode": {
                "enabled": True,
                "command": "opencode",
                "args": ["acp"],
                "env": {},
                "trusted": False,
                "tool_parse_mode": "update_detail",
                "stdio_buffer_limit_bytes": 52428800,
            },
        },
    }
    r = await c.put(f"/api/agents/{agent_id}/acp", headers=auth, json=payload)
    assert r.status_code == 200
    assert r.json()["tool_enabled"] is True
    assert r.json()["runners"]["opencode"]["enabled"] is True

    r = await c.get(f"/api/agents/{agent_id}/acp/opencode", headers=auth)
    assert r.status_code == 200
    assert r.json()["command"] == "opencode"


async def test_acp_custom_runner_crud(env) -> None:
    c, _srv, auth, agent_id = env

    runner = {
        "enabled": True,
        "command": "python",
        "args": ["-m", "my_runner"],
        "env": {"FOO": "bar"},
        "trusted": True,
        "tool_parse_mode": "call_title",
        "stdio_buffer_limit_bytes": 52428800,
    }
    r = await c.put(f"/api/agents/{agent_id}/acp/my_runner", headers=auth, json=runner)
    assert r.status_code == 200
    assert r.json()["env"]["FOO"] == "bar"

    r = await c.delete(f"/api/agents/{agent_id}/acp/my_runner", headers=auth)
    assert r.status_code == 204

    r = await c.get(f"/api/agents/{agent_id}/acp/my_runner", headers=auth)
    assert r.status_code == 404


async def test_acp_builtin_runner_cannot_delete(env) -> None:
    c, _srv, auth, agent_id = env
    r = await c.delete(f"/api/agents/{agent_id}/acp/opencode", headers=auth)
    assert r.status_code == 403


@pytest.mark.parametrize(
    ("name", "command", "args"),
    [
        ("hermes", "hermes", ["acp"]),
        ("grok_build", "grok", ["agent", "stdio"]),
        ("openclaw", "openclaw", ["acp"]),
    ],
)
async def test_extended_global_presets_are_disabled_editable_and_not_deletable(
    env, name: str, command: str, args: list[str]
) -> None:
    c, _srv, auth, _agent_id = env
    response = await c.get("/api/acp", headers=auth)
    assert response.status_code == 200
    runner = response.json()["runners"][name]
    assert runner["enabled"] is False
    assert runner["command"] == command
    assert runner["args"] == args
    assert runner["env"] == {}

    response = await c.put(
        f"/api/acp/{name}", headers=auth, json={**runner, "command": "custom-launcher"}
    )
    assert response.status_code == 200
    assert response.json()["command"] == "custom-launcher"
    response = await c.get(f"/api/acp/{name}", headers=auth)
    assert response.json()["command"] == "custom-launcher"
    response = await c.delete(f"/api/acp/{name}", headers=auth)
    assert response.status_code == 403


async def test_acp_tool_allowed_for_scoped_root_dir(env) -> None:
    """Directory sandbox does not block enabling outbound acp_runner."""
    c, _srv, auth, _agent_id = env
    from tests.support.auth import create_agent

    agent_id = await create_agent(
        c,
        auth,
        name="acp-scoped",
        config={
            "backend": {
                "type": "local_shell",
                "root_dir": "/tmp/octop-acp-scoped",
                "virtual_mode": True,
            }
        },
    )
    r = await c.put(
        f"/api/agents/{agent_id}/acp/tool",
        headers=auth,
        json={"tool_enabled": True},
    )
    assert r.status_code == 200
    assert r.json()["tool_enabled"] is True
