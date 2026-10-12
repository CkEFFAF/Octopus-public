"""0010: transition OCTOP_DEVICE_SERVER + scoped allow-insecure."""

from __future__ import annotations

import pytest
from click.testing import CliRunner

from octop.cli.main import cli
from octop.infra.devices.client import validate_server_url
from octop.infra.devices.executor import DeviceExecutionError
from octop.infra.devices.first_run import resolve_server_and_insecure, resolve_server_url
from octop.infra.devices.network import DeviceNetwork
from octop.infra.devices.protocol import (
    DEFAULT_DEVICE_SERVER,
    is_transition_insecure_allowed,
)

TRANSITION = "http://111.228.42.228:8188"


def test_default_constant_stays_https():
    assert DEFAULT_DEVICE_SERVER == "https://octop.effaf.me"


def test_transition_whitelist_only_exact_hub():
    assert is_transition_insecure_allowed(TRANSITION) is True
    assert is_transition_insecure_allowed(TRANSITION + "/") is True
    assert is_transition_insecure_allowed("http://111.228.42.228:8188/path") is True
    assert is_transition_insecure_allowed("http://111.228.42.228") is False  # wrong port
    assert is_transition_insecure_allowed("http://111.228.42.228:80") is False
    assert is_transition_insecure_allowed("https://111.228.42.228:8188") is False
    assert is_transition_insecure_allowed("http://192.168.1.2:8188") is False
    assert is_transition_insecure_allowed("http://evil.example:8188") is False
    assert is_transition_insecure_allowed("https://octop.effaf.me") is False


def test_validate_still_rejects_other_remote_http():
    with pytest.raises(DeviceExecutionError, match="allow-insecure"):
        validate_server_url("http://192.168.1.2:8088")
    # Whitelist does not change validate_server_url itself — callers pass allow_insecure.
    with pytest.raises(DeviceExecutionError, match="allow-insecure"):
        validate_server_url(TRANSITION)
    assert validate_server_url(TRANSITION, allow_insecure=True) == TRANSITION.rstrip("/")


def test_resolve_auto_insecure_for_transition(monkeypatch):
    monkeypatch.setenv("OCTOP_DEVICE_SERVER", TRANSITION)
    url, insecure = resolve_server_and_insecure(None)
    assert url == TRANSITION
    assert insecure is True
    assert resolve_server_url(None) == TRANSITION


def test_resolve_without_env_stays_https(monkeypatch):
    monkeypatch.delenv("OCTOP_DEVICE_SERVER", raising=False)
    url, insecure = resolve_server_and_insecure(None)
    assert url == DEFAULT_DEVICE_SERVER
    assert insecure is False


@pytest.fixture
def enrollment(monkeypatch):
    requests = []
    runs = []
    logins = []

    def enroll(url, payload, *, authorization=None):
        requests.append((url, payload, authorization))
        return {"device": {"device_id": "joined-device"}, "device_token": "odv_private-token"}

    def login(server_url, username, password, *, allow_insecure=False, captcha_token=None):
        logins.append((server_url, username, password, allow_insecure))
        return "jwt-session-for-enroll"

    async def run(network, notify):
        runs.append(network.controllers())

    monkeypatch.setattr("octop.infra.devices.client._enroll_http", enroll)
    monkeypatch.setattr("octop.infra.devices.client.account_login", login)
    monkeypatch.setattr("octop.cli.device_cmd.account_login", login)
    monkeypatch.setattr("octop.infra.devices.first_run.account_login", login)
    monkeypatch.setattr(DeviceNetwork, "run", run)
    return {"requests": requests, "runs": runs, "logins": logins}


def test_join_transition_env_skips_insecure_confirm(tmp_path, monkeypatch, enrollment):
    """AC-T02/T04: transition env prefills hub; no insecure confirm; account only."""
    monkeypatch.setattr("octop.cli.device_startup_cmd.platform.system", lambda: "Linux")
    monkeypatch.setenv("OCTOP_DEVICE_SERVER", TRANSITION)
    state = tmp_path / "state"
    result = CliRunner().invoke(
        cli,
        ["device", "join", "--state", str(state)],
        input="\nBox\nowner\nsecret\ny\n",
    )
    assert result.exit_code == 0, result.output
    assert enrollment["logins"][0][0] == TRANSITION
    assert enrollment["logins"][0][3] is True  # allow_insecure
    assert enrollment["requests"][0][0] == TRANSITION
    # confirm prompt text should not appear for whitelist
    assert "未加密" not in result.output


def test_join_other_remote_http_still_asks(tmp_path, monkeypatch, enrollment):
    monkeypatch.setattr("octop.cli.device_startup_cmd.platform.system", lambda: "Linux")
    monkeypatch.delenv("OCTOP_DEVICE_SERVER", raising=False)
    state = tmp_path / "state"
    result = CliRunner().invoke(
        cli,
        ["device", "join", "--server", "http://192.168.1.2:8088", "--state", str(state)],
        input="Box\nowner\nsecret\nn\n",
    )
    assert result.exit_code != 0
