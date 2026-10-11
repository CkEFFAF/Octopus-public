from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
from click.testing import CliRunner

from octop.cli.main import cli
from octop.infra.devices.executor import DeviceExecutionError, save_private_json
from octop.infra.devices.network import DeviceNetwork


def saved_network(tmp_path: Path, *, controller: str = "default", server: str = "https://old.test"):
    network = DeviceNetwork(tmp_path / "state")
    directory = network.state_dir
    if controller != "default":
        directory = directory / "controllers" / controller
        directory.mkdir(parents=True)
        save_private_json(network.catalog_path, {"version": 1, "controllers": [{"id": controller}]})
    state = {
        "server_url": server,
        "device_id": "device-original",
        "device_token": "odv_secret-must-stay-private",
        "allow_insecure": server.startswith("http:"),
        "policy": {
            "permissions": ["files_read", "command_exec"],
            "roots": [{"id": "root", "name": "Share", "path": str(tmp_path / "share")}],
            "desktop_enabled": False,
            "control_enabled": False,
            "command_enabled": True,
        },
        "extension": {"keep": "未知配置"},
    }
    save_private_json(directory / "device.json", state)
    save_private_json(directory / "operations.json", {"one": {"state": "completed"}})
    return network, directory, state


@pytest.mark.parametrize("controller", ["default", "a" * 32])
def test_relocation_only_changes_endpoint_and_preserves_identity_policy_and_journal(
    tmp_path, monkeypatch, controller
):
    network, directory, original = saved_network(tmp_path, controller=controller)
    journal = (directory / "operations.json").read_bytes()
    catalog = network.catalog_path.read_bytes() if network.catalog_path.exists() else None

    def forbidden(*args, **kwargs):
        pytest.fail("offline relocation must not send credentials or contact a management host")

    monkeypatch.setattr("octop.infra.devices.client._enroll_http", forbidden)
    monkeypatch.setattr("octop.infra.devices.client.DeviceClient.run", forbidden)
    result = network.relocate_controller(
        controller, expected_server="https://OLD.test:443/", server_url="https://new.test/"
    )
    assert json.loads((directory / "device.json").read_text(encoding="utf-8")) == {
        **original,
        "server_url": "https://new.test",
        "allow_insecure": False,
    }
    assert (directory / "operations.json").read_bytes() == journal
    assert (network.catalog_path.read_bytes() if network.catalog_path.exists() else None) == catalog
    assert result == {
        "id": controller,
        "server_url": "https://new.test",
        "device_id": "device-original",
    }
    assert "odv_" not in json.dumps(result)
    if os.name != "nt":
        assert (directory / "device.json").stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    ("old", "new", "insecure"),
    [
        ("http://old.test", "http://new.test", True),
        ("http://old.test", "https://new.test", False),
        ("https://old.test", "http://127.0.0.1:8188", False),
    ],
)
def test_relocation_supported_transport_changes(tmp_path, old, new, insecure):
    network, directory, original = saved_network(tmp_path, server=old)
    network.relocate_controller(
        "default", expected_server=old, server_url=new, allow_insecure=insecure
    )
    assert json.loads((directory / "device.json").read_text(encoding="utf-8")) == {
        **original,
        "server_url": new,
        "allow_insecure": insecure,
    }


@pytest.mark.parametrize("new", ["http://new.test", "http://10.0.0.2:8188", "http://[::2]"])
def test_https_never_downgrades_to_remote_http_even_with_opt_in(tmp_path, new):
    network, directory, _ = saved_network(tmp_path)
    before = (directory / "device.json").read_bytes()
    with pytest.raises(DeviceExecutionError, match="HTTPS.*remote HTTP"):
        network.relocate_controller(
            "default", expected_server="https://old.test", server_url=new, allow_insecure=True
        )
    assert (directory / "device.json").read_bytes() == before


@pytest.mark.parametrize("new", ["http://new.test", "http://127.0.0.1:8188"])
def test_http_relocation_requires_explicit_insecure_opt_in(tmp_path, new):
    network, directory, _ = saved_network(tmp_path, server="http://old.test")
    before = (directory / "device.json").read_bytes()
    with pytest.raises(DeviceExecutionError, match="--allow-insecure"):
        network.relocate_controller("default", expected_server="http://old.test", server_url=new)
    assert (directory / "device.json").read_bytes() == before


@pytest.mark.parametrize(
    "expected", ["https://other.test", "https://old.test:444", "https://old.test/path"]
)
def test_old_endpoint_must_match_before_any_change(tmp_path, expected):
    network, directory, _ = saved_network(tmp_path)
    before = (directory / "device.json").read_bytes()
    with pytest.raises(DeviceExecutionError, match="does not match"):
        network.relocate_controller(
            "default", expected_server=expected, server_url="https://new.test"
        )
    assert (directory / "device.json").read_bytes() == before


@pytest.mark.parametrize("controller", ["../outside", "b" * 32])
def test_unknown_or_invalid_controller_does_not_mutate_saved_state(tmp_path, controller):
    network, directory, _ = saved_network(tmp_path)
    before = (directory / "device.json").read_bytes()
    with pytest.raises(
        DeviceExecutionError, match="invalid controller identifier|controller not found"
    ):
        network.relocate_controller(
            controller, expected_server="https://old.test", server_url="https://new.test"
        )
    assert (directory / "device.json").read_bytes() == before


@pytest.mark.parametrize(
    "url",
    [
        "ftp://new.test",
        "https:///missing-host",
        "https://user:odv_secret-must-stay-private@new.test",
        "https://new.test?token=odv_secret-must-stay-private",
        "https://new.test#fragment",
        "https://new.test:99999",
        "https://new.test:invalid",
        "https://new.test/\npath",
        "https://bad host",
        "https://new.test\\other",
    ],
)
@pytest.mark.parametrize("argument", ["expected_server", "server_url"])
def test_illegal_relocation_urls_are_rejected_without_mutation_or_secret_output(
    tmp_path, url, argument
):
    network, directory, _ = saved_network(tmp_path)
    before = (directory / "device.json").read_bytes()
    values = {
        "expected_server": "https://old.test",
        "server_url": "https://new.test",
        argument: url,
    }
    with pytest.raises(DeviceExecutionError) as failure:
        network.relocate_controller("default", **values)
    assert "odv_secret" not in str(failure.value)
    assert (directory / "device.json").read_bytes() == before


def test_duplicate_endpoint_in_other_profile_is_rejected(tmp_path):
    network, directory, _ = saved_network(tmp_path)
    second = network.state_dir / "controllers" / ("a" * 32)
    second.mkdir(parents=True)
    state = json.loads((directory / "device.json").read_text(encoding="utf-8"))
    save_private_json(
        second / "device.json", {**state, "server_url": "https://SECOND.test:443/path/"}
    )
    save_private_json(network.catalog_path, {"version": 1, "controllers": [{"id": "a" * 32}]})
    before = (directory / "device.json").read_bytes()
    with pytest.raises(DeviceExecutionError, match="already configured"):
        network.relocate_controller(
            "default", expected_server="https://old.test", server_url="https://second.test/path"
        )
    assert (directory / "device.json").read_bytes() == before


def test_running_network_excludes_relocation(tmp_path):
    network, directory, _ = saved_network(tmp_path)
    other = DeviceNetwork(network.state_dir)
    before = (directory / "device.json").read_bytes()
    with network.locked(), pytest.raises(DeviceExecutionError, match="stop it"):
        other.relocate_controller(
            "default", expected_server="https://old.test", server_url="https://new.test"
        )
    assert (directory / "device.json").read_bytes() == before


def test_failed_atomic_write_preserves_original_identity(tmp_path, monkeypatch):
    network, directory, _ = saved_network(tmp_path)
    before = (directory / "device.json").read_bytes()

    def fail_replace(*args, **kwargs):
        raise OSError("simulated disk failure")

    monkeypatch.setattr("octop.infra.devices.executor.os.replace", fail_replace)
    with pytest.raises(OSError, match="disk failure"):
        network.relocate_controller(
            "default", expected_server="https://old.test", server_url="https://new.test"
        )
    assert (directory / "device.json").read_bytes() == before
    assert list(directory.glob(".state-*")) == []


@pytest.mark.parametrize("accept", [True, False])
def test_cli_requires_confirmation_with_exact_addresses_and_migration_trust(tmp_path, accept):
    network, directory, _ = saved_network(tmp_path)
    before = (directory / "device.json").read_bytes()
    result = CliRunner().invoke(
        cli,
        [
            "device",
            "relocate-controller",
            "default",
            "--from-server",
            "https://old.test",
            "--server",
            "https://new.test",
            "--state",
            str(network.state_dir),
        ],
        input="y\n" if accept else "n\n",
    )
    assert "https://old.test" in result.output and "https://new.test" in result.output
    assert "same management instance" in result.output and "trusted" in result.output
    assert "odv_secret" not in result.output
    assert result.exit_code == (0 if accept else 1), result.output
    assert ((directory / "device.json").read_bytes() != before) is accept


def test_cli_yes_is_explicit_attestation_and_help_directs_new_hosts_to_enrollment(tmp_path):
    network, directory, _ = saved_network(tmp_path)
    result = CliRunner().invoke(
        cli,
        [
            "device",
            "relocate-controller",
            "default",
            "--from-server",
            "https://old.test",
            "--server",
            "https://new.test",
            "--state",
            str(network.state_dir),
            "--yes",
        ],
    )
    assert result.exit_code == 0, result.output
    assert (
        json.loads((directory / "device.json").read_text(encoding="utf-8"))["server_url"]
        == "https://new.test"
    )
    assert "odv_secret" not in result.output
    help_result = CliRunner().invoke(cli, ["device", "relocate-controller", "--help"])
    assert help_result.exit_code == 0
    assert "same management instance" in help_result.output
    assert "add-controller" in help_result.output


def test_cli_invalid_credential_url_never_echoes_secret(tmp_path):
    network, directory, _ = saved_network(tmp_path)
    before = (directory / "device.json").read_bytes()
    result = CliRunner().invoke(
        cli,
        [
            "device",
            "relocate-controller",
            "default",
            "--from-server",
            "https://old.test",
            "--server",
            "https://user:odv_secret-must-stay-private@new.test",
            "--state",
            str(network.state_dir),
        ],
    )
    assert result.exit_code != 0
    assert "odv_secret" not in result.output
    assert (directory / "device.json").read_bytes() == before
