"""First-launch consent and saved-identity reuse through the public CLI."""

from __future__ import annotations

from pathlib import Path

import pytest
from click.testing import CliRunner

from octop.cli.main import cli
from octop.infra.devices.network import DeviceNetwork


@pytest.fixture
def enrollment(monkeypatch):
    requests = []
    runs = []

    def enroll(url, payload):
        requests.append((url, payload))
        return {"device": {"device_id": "joined-device"}, "device_token": "odv_private-token"}

    async def run(network, notify):
        runs.append(network.controllers())

    monkeypatch.setattr("octop.infra.devices.client._enroll_http", enroll)
    monkeypatch.setattr(DeviceNetwork, "run", run)
    return requests, runs


@pytest.mark.parametrize("credential", ["12345678", "oak_private-enrollment-key"])
def test_join_hidden_credential_and_confirmed_windows_desktop(
    tmp_path, monkeypatch, enrollment, credential
):
    monkeypatch.setattr("octop.cli.device_startup_cmd.platform.system", lambda: "Windows")
    state = tmp_path / "device-state"
    result = CliRunner().invoke(
        cli,
        ["device", "join", "--server", "https://manager.test", "--state", str(state)],
        input=f"Windows PC\n2\n\nn\ny\n2\n{credential}\n",
    )
    assert result.exit_code == 0, result.output
    requests, runs = enrollment
    url, payload = requests[0]
    assert url == "https://manager.test"
    assert payload["name"] == "Windows PC"
    assert set(payload["capabilities"]) == {
        "files_read",
        "files_write",
        "desktop_view",
        "desktop_control",
        "command_exec",
        "acp_run",
    }
    assert payload["roots"][0]["name"] == "OctopShare"
    assert (tmp_path / "OctopShare").is_dir()
    assert payload.get("access_key") == (credential if credential.startswith("oak_") else None)
    assert payload.get("pairing_code") == (None if credential.startswith("oak_") else credential)
    assert credential not in result.output and "odv_private-token" not in result.output
    assert len(runs) == 1 and runs[0][0]["device_id"] == "joined-device"
    assert not list(state.glob("*.service"))


def test_linux_join_commands_require_final_consent(tmp_path, monkeypatch, enrollment):
    monkeypatch.setattr("octop.cli.device_startup_cmd.platform.system", lambda: "Linux")
    result = CliRunner().invoke(
        cli,
        ["device", "join", "--server", "https://manager.test", "--state", str(tmp_path / "state")],
        input="GPU Server\n1\n\nn\ny\n2\n87654321\n",
    )
    assert result.exit_code == 0, result.output
    payload = enrollment[0][0][1]
    assert set(payload["capabilities"]) == {"files_read", "files_write", "command_exec", "acp_run"}
    assert "不是系统沙箱" in result.output
    assert "2 桌面和文件" not in result.output


def test_join_acp_requires_separate_local_consent(tmp_path, monkeypatch, enrollment):
    monkeypatch.setattr("octop.cli.device_startup_cmd.platform.system", lambda: "Linux")
    result = CliRunner().invoke(
        cli,
        ["device", "join", "--server", "https://manager.test", "--state", str(tmp_path / "state")],
        input="GPU Server\n1\n\ny\ny\n2\n87654321\n",
    )
    assert result.exit_code == 0, result.output
    assert "acp_run" in enrollment[0][0][1]["capabilities"]


def test_declining_join_does_not_enroll_or_create_share(tmp_path, enrollment):
    share = tmp_path / "new-share"
    result = CliRunner().invoke(
        cli,
        ["device", "join", "--server", "https://manager.test", "--state", str(tmp_path / "state")],
        input=f"My PC\n3\n{share}\nn\n",
    )
    assert result.exit_code != 0
    assert enrollment == ([], [])
    assert not share.exists()
    assert "隐藏输入" not in result.output


@pytest.mark.parametrize(
    "server",
    ["https://user:password@manager.test", "https://manager.test?key=x", "http://manager.test"],
)
def test_invalid_or_unaccepted_transport_stops_before_credential(tmp_path, enrollment, server):
    result = CliRunner().invoke(
        cli,
        ["device", "join", "--server", server, "--state", str(tmp_path / "state")],
        input="n\n",
    )
    assert result.exit_code != 0
    assert enrollment == ([], [])
    assert "隐藏输入" not in result.output


def test_accepted_http_still_needs_permission_confirmation(tmp_path, enrollment):
    result = CliRunner().invoke(
        cli,
        ["device", "join", "--server", "http://manager.test", "--state", str(tmp_path / "state")],
        input="y\nMy PC\n3\n\ny\n2\n11223344\n",
    )
    assert result.exit_code == 0, result.output
    assert {"files_read", "files_write", "command_exec", "acp_run"} <= set(enrollment[0][0][1]["capabilities"])


def test_join_reuses_saved_identity_without_new_authorization(tmp_path, enrollment):
    runner = CliRunner()
    args = ["device", "join", "--state", str(tmp_path / "state")]
    first = runner.invoke(
        cli, [*args, "--server", "https://manager.test"], input="PC\n3\n\ny\n2\n12345678\n"
    )
    assert first.exit_code == 0, first.output
    second = runner.invoke(cli, args)
    assert second.exit_code == 0, second.output
    assert len(enrollment[0]) == 1 and len(enrollment[1]) == 2
    assert enrollment[1][0] == enrollment[1][1]
    assert "权限方案" not in second.output
    rejected = runner.invoke(cli, [*args, "--server", "https://other.test"])
    assert rejected.exit_code != 0 and "add-controller" in rejected.output
    assert len(enrollment[0]) == 1


def test_portable_launchers_first_launch_and_reconnect_share_entry(repo_root: Path):
    # Real launchers must reach the tested wizard without credentials in argv.
    for filename in ("start-device.bat", "start-device.sh"):
        text = (repo_root / "desktop" / "portable" / filename).read_text(encoding="utf-8")
        assert "device join --state" in text
        assert "device connect --state" in text  # scripted legacy enrollment remains available


def test_join_account_password_enroll(tmp_path, monkeypatch, enrollment):
    """0004: join mode 1 logs in then enrolls with Bearer; JWT not kept in state."""
    monkeypatch.setattr("octop.cli.device_startup_cmd.platform.system", lambda: "Windows")
    tokens = []

    def fake_login(server_url, username, password, *, allow_insecure=False, captcha_token=None):
        tokens.append((server_url, username, password))
        return "jwt-session-for-enroll"

    captured = []

    def enroll(url, payload, *, authorization=None):
        captured.append((url, payload, authorization))
        return {"device": {"device_id": "acct-device"}, "device_token": "odv_acct"}

    monkeypatch.setattr("octop.infra.devices.client.account_login", fake_login)
    monkeypatch.setattr("octop.cli.device_cmd.account_login", fake_login)
    monkeypatch.setattr("octop.infra.devices.client._enroll_http", enroll)
    state = tmp_path / "acct-state"
    result = CliRunner().invoke(
        cli,
        ["device", "join", "--server", "https://manager.test", "--state", str(state)],
        input="Acct PC\n3\n\ny\n1\nowner\nsecret-pass\n",
    )
    assert result.exit_code == 0, result.output
    assert tokens == [("https://manager.test", "owner", "secret-pass")]
    assert captured[0][2] == "Bearer jwt-session-for-enroll"
    assert "access_key" not in captured[0][1] and "pairing_code" not in captured[0][1]
    state_blob = "\n".join(path.read_text(encoding="utf-8") for path in state.rglob("*.json"))
    assert "jwt-session-for-enroll" not in state_blob
    assert "secret-pass" not in state_blob
    assert "odv_acct" in state_blob
