from __future__ import annotations

import json

from click.testing import CliRunner

from octop.cli.main import cli


def test_device_commands_include_guided_setup_and_network() -> None:
    result = CliRunner().invoke(cli, ["device", "--help"])
    assert result.exit_code == 0
    for name in (
        "run",
        "controllers",
        "add-controller",
        "remove-controller",
        "setup",
        "join",
        "autostart",
    ):
        assert name in result.output


def test_add_controller_hidden_prompt_and_safe_listing(tmp_path, monkeypatch) -> None:
    requests = []

    def enroll(url, payload):
        requests.append(payload)
        return {"device": {"device_id": "new-device"}, "device_token": "odv_secret-token"}

    monkeypatch.setattr("octop.infra.devices.client._enroll_http", enroll)
    runner = CliRunner()
    state = tmp_path / "private"
    result = runner.invoke(
        cli,
        ["device", "add-controller", "--server", "https://host.test", "--state", str(state)],
        input="oak_hidden-enrollment-secret\n",
    )
    assert result.exit_code == 0, result.output
    assert requests[0]["access_key"] == "oak_hidden-enrollment-secret"
    assert "oak_hidden" not in result.output
    listing = runner.invoke(cli, ["device", "controllers", "--state", str(state)])
    assert listing.exit_code == 0
    assert json.loads(listing.output)[0]["server_url"] == "https://host.test"
    assert "secret" not in listing.output


def test_no_saved_network_has_actionable_error(tmp_path) -> None:
    result = CliRunner().invoke(cli, ["device", "run", "--state", str(tmp_path / "private")])
    assert result.exit_code != 0
    assert "device setup" in result.output


def test_add_controller_control_and_command_require_explicit_consent(tmp_path) -> None:
    runner = CliRunner()
    args = [
        "device",
        "add-controller",
        "--server",
        "https://host.test",
        "--state",
        str(tmp_path / "private"),
    ]
    assert "--control requires --desktop" in runner.invoke(cli, [*args, "--control"]).output
    assert "shared working directory" in runner.invoke(cli, [*args, "--allow-command"]).output
