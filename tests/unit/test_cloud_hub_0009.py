"""0009 cloud hub static gates (ops scripts + docs); defaults upgraded by 0027."""

from __future__ import annotations

from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OPS = REPO / "ops" / "cloud-hub"


def test_ops_scripts_exist() -> None:
    for name in (
        "install-hub.sh",
        "smoke-hub.sh",
        "octop-hub.service.in",
        "octop-hub.root.service.example",
        "octop-hub.ubuntu.service.example",
        "README.md",
    ):
        assert (OPS / name).is_file(), name


def test_unit_uses_octop_home_not_cli_home_flag() -> None:
    for name in (
        "octop-hub.service.in",
        "octop-hub.root.service.example",
        "octop-hub.ubuntu.service.example",
        "octop-hub.octop.service.example",
    ):
        text = (OPS / name).read_text(encoding="utf-8")
        assert "OCTOP_HOME=" in text
        assert "OCTOP_BIND_HOST=" in text
        assert "OCTOP_PORT=" in text
        assert "Restart=on-failure" in text
        assert "octop run" in text
        # no fake CLI flag in ExecStart
        assert "--home" not in text.split("ExecStart", 1)[-1]


def test_root_example_is_bootstrap_only_loopback() -> None:
    text = (OPS / "octop-hub.root.service.example").read_text(encoding="utf-8")
    assert "WorkingDirectory=/root/octopus" in text
    assert "OCTOP_HOME=/root/OctopData" in text
    service = text.split("[Service]", 1)[-1].split("[Install]", 1)[0]
    assert "User=" not in service  # root unit omits User= in [Service]
    assert "OCTOP_BIND_HOST=127.0.0.1" in text
    assert "BOOTSTRAP-ONLY" in text or "bootstrap" in text.lower()


def test_ubuntu_example_has_user_and_loopback() -> None:
    text = (OPS / "octop-hub.ubuntu.service.example").read_text(encoding="utf-8")
    assert "User=ubuntu" in text
    assert "OCTOP_HOME=/home/ubuntu/OctopData" in text
    assert "OCTOP_BIND_HOST=127.0.0.1" in text


def test_install_hub_is_system_unit() -> None:
    text = (OPS / "install-hub.sh").read_text(encoding="utf-8")
    common = (OPS / "_hub_common.sh").read_text(encoding="utf-8")
    assert "HUB_UNIT_NAME" in text or "HUB_UNIT_NAME" in common
    assert "/etc/systemd/system" in common
    assert "enable --now" in text
    assert "HUB_OCTOP_HOME" in text
    assert "must run as root" in text or "must run as root" in common


def test_ops_doc_covers_decisions() -> None:
    text = (REPO / "docs/octopus/cloud-hub-ops.md").read_text(encoding="utf-8")
    assert "111.228.42.228" in text
    assert "https://octop.effaf.me" in text
    assert "OCTOP_HOME" in text
    assert "octop-hub" in text
    assert "--allow-insecure" in text
    assert "ops/cloud-hub/install-hub.sh" in text
    # product default must not be IP-only
    assert "禁止" in text or "勿写入开箱包默认" in text
    # 0027 production defaults
    assert "127.0.0.1" in text
    assert "90-octop" in text


def test_spec_accepted_and_octop_home() -> None:
    text = (REPO / "docs/specs/0009-cloud-hub-production.md").read_text(encoding="utf-8")
    assert "Accepted" in text
    assert "2026-10-12.3" in text
    assert "OCTOP_HOME" in text
    assert "ops/cloud-hub/" in text
    assert "DEC-005" in text and "DEC-006" in text
    assert "0027" in text  # Errata cross-link


def test_portable_default_server_is_not_cloud_ip() -> None:
    """Default documented server is HTTPS filing domain; transition IP is opt-in only."""
    readme = (REPO / "desktop/portable/templates/README.txt").read_text(encoding="utf-8")
    assert "https://octop.effaf.me" in readme
    # 0010: README may document transition HTTP IP via open-device-transition / OCTOP_DEVICE_SERVER
    assert "open-device-transition" in readme or "OCTOP_DEVICE_SERVER" in readme


def test_tunnel_doc_mentions_cloud_origin() -> None:
    text = (REPO / "docs/octopus/cloudflare-tunnel-entry.md").read_text(encoding="utf-8")
    assert "云机" in text
    assert "octop.effaf.me" in text
