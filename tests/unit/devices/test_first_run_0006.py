"""0006 first-run UU path: default server, account enroll, reconnect."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from octop.cli.main import cli
from octop.infra.devices.network import DeviceNetwork
from octop.infra.devices.protocol import DEFAULT_DEVICE_SERVER


@pytest.fixture
def enrollment(monkeypatch):
    requests = []
    runs = []
    logins = []

    def enroll(url, payload, *, authorization=None):
        requests.append((url, payload, authorization))
        return {"device": {"device_id": "joined-device"}, "device_token": "odv_private-token"}

    def login(server_url, username, password, *, allow_insecure=False, captcha_token=None):
        logins.append((server_url, username, password))
        return "jwt-session-for-enroll"

    async def run(network, notify):
        runs.append(network.controllers())

    monkeypatch.setattr("octop.infra.devices.client._enroll_http", enroll)
    monkeypatch.setattr("octop.infra.devices.client.account_login", login)
    monkeypatch.setattr("octop.cli.device_cmd.account_login", login)
    monkeypatch.setattr("octop.infra.devices.first_run.account_login", login)
    monkeypatch.setattr(DeviceNetwork, "run", run)
    return {"requests": requests, "runs": runs, "logins": logins}


def test_default_server_constant():
    assert DEFAULT_DEVICE_SERVER == "https://octop.effaf.me"


def test_join_uu_account_password_uses_default_server(tmp_path, monkeypatch, enrollment):
    """AC-001/AC-004: empty server prompt accepts product default; account enrolls."""
    monkeypatch.setattr("octop.cli.device_startup_cmd.platform.system", lambda: "Windows")
    state = tmp_path / "device-state"
    result = CliRunner().invoke(
        cli,
        ["device", "join", "--state", str(state)],
        input="\nMy PC\nowner\nsecret-pass\ny\n",
    )
    assert result.exit_code == 0, result.output
    assert enrollment["logins"][0][0] == DEFAULT_DEVICE_SERVER
    assert enrollment["logins"][0][1:] == ("owner", "secret-pass")
    url, payload, auth = enrollment["requests"][0]
    assert url == DEFAULT_DEVICE_SERVER
    assert auth == "Bearer jwt-session-for-enroll"
    assert payload["name"] == "My PC"
    assert "pairing_code" not in payload and "access_key" not in payload
    state_blob = "\n".join(path.read_text(encoding="utf-8") for path in state.rglob("*.json"))
    assert "secret-pass" not in state_blob
    assert "jwt-session-for-enroll" not in state_blob
    assert "odv_private-token" in state_blob
    assert len(enrollment["runs"]) == 1


def test_join_account_token_skips_password(tmp_path, monkeypatch, enrollment):
    """AC-005: existing short-lived token skips password prompt."""
    monkeypatch.setattr("octop.cli.device_startup_cmd.platform.system", lambda: "Linux")
    state = tmp_path / "state"
    result = CliRunner().invoke(
        cli,
        [
            "device",
            "join",
            "--server",
            "https://manager.test",
            "--account-token",
            "jwt-already",
            "--name",
            "GPU",
            "--state",
            str(state),
        ],
        input="y\n",
    )
    assert result.exit_code == 0, result.output
    assert enrollment["logins"] == []
    assert enrollment["requests"][0][2] == "Bearer jwt-already"


def test_join_reconnect_skips_wizard(tmp_path, monkeypatch, enrollment):
    """AC-006: configured device-state reconnects without enrollment."""
    monkeypatch.setattr("octop.cli.device_startup_cmd.platform.system", lambda: "Windows")
    state = tmp_path / "state"
    first = CliRunner().invoke(
        cli,
        ["device", "join", "--server", "https://manager.test", "--state", str(state)],
        input="PC\nowner\nsecret\ny\n",
    )
    assert first.exit_code == 0, first.output
    second = CliRunner().invoke(cli, ["device", "join", "--state", str(state)])
    assert second.exit_code == 0, second.output
    assert len(enrollment["requests"]) == 1
    assert len(enrollment["runs"]) == 2
    assert "账号" not in second.output


def test_join_advanced_pair_code_still_works(tmp_path, monkeypatch, enrollment):
    monkeypatch.setattr("octop.cli.device_startup_cmd.platform.system", lambda: "Windows")
    state = tmp_path / "device-state"
    result = CliRunner().invoke(
        cli,
        ["device", "join", "--advanced", "--server", "https://manager.test", "--state", str(state)],
        input="Windows PC\n2\n\nn\ny\n2\n12345678\n",
    )
    assert result.exit_code == 0, result.output
    url, payload, _auth = enrollment["requests"][0]
    assert url == "https://manager.test"
    assert payload.get("pairing_code") == "12345678"
    assert (tmp_path / "OctopShare").is_dir()


def test_open_device_launcher_points_at_first_run(repo_root: Path):
    for filename in ("open-device.bat", "open-device.sh"):
        text = (repo_root / "desktop" / "portable" / filename).read_text(encoding="utf-8")
        assert "device first-run --state" in text


def test_first_run_cli_flag_delegates_to_join(tmp_path, monkeypatch, enrollment):
    monkeypatch.setattr("octop.cli.device_startup_cmd.platform.system", lambda: "Linux")
    monkeypatch.setattr("octop.infra.devices.first_run.gui_available", lambda: True)
    state = tmp_path / "state"
    result = CliRunner().invoke(
        cli,
        ["device", "first-run", "--cli", "--server", "https://manager.test", "--state", str(state)],
        input="Box\nowner\nsecret\ny\n",
    )
    assert result.exit_code == 0, result.output
    assert enrollment["logins"][0][0] == "https://manager.test"
