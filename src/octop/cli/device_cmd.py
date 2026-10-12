"""Opt-in native device connection, separate from the local Octop server."""

from __future__ import annotations

import asyncio
import json
import platform
from pathlib import Path

import click

from octop.infra.devices.client import DeviceClient
from octop.infra.devices.executor import DeviceExecutionError, DeviceExecutor
from octop.infra.devices.network import DeviceNetwork, validate_relocation_url


@click.group()
def device() -> None:
    """Connect this Windows/Linux device to independently trusted management hosts."""


@device.command("connect")
@click.option("--server", help="Control center HTTPS URL (HTTP allowed on loopback).")
@click.option("--pair-code", help="Single-use code from your account's Devices page.")
@click.option(
    "--access-key",
    prompt=False,
    help="Account access key (prefer --key-file to keep it out of process arguments).",
)
@click.option(
    "--key-file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    help="Read an account access key from a private UTF-8 file.",
)
@click.option("--name", help="Name shown in your account's device list.")
@click.option(
    "--share",
    multiple=True,
    type=click.Path(exists=True, file_okay=False, path_type=Path),
    help="Share an existing directory; may be repeated.",
)
@click.option(
    "--read-only", is_flag=True, help="Permit reads, disable writes to every shared directory."
)
@click.option(
    "--desktop",
    is_flag=True,
    help="Permit viewing this desktop (requires native capture dependencies).",
)
@click.option("--control", is_flag=True, help="Permit keyboard/mouse input; requires --desktop.")
@click.option(
    "--allow-command",
    is_flag=True,
    help="Permit confirmed argv commands on this OS; this is not a filesystem sandbox.",
)
@click.option(
    "--allow-acp",
    is_flag=True,
    help="Permit ACP agents installed and signed in on this device; requires a writable --share directory.",
)
@click.option(
    "--allow-insecure", is_flag=True, help="Explicitly permit remote HTTP for local development."
)
@click.option(
    "--state",
    type=click.Path(file_okay=False, path_type=Path),
    default=None,
    help="Private device state directory (default: ~/.octop-device).",
)
def connect(
    server: str | None,
    pair_code: str | None,
    access_key: str | None,
    key_file: Path | None,
    name: str | None,
    share: tuple[Path, ...],
    read_only: bool,
    desktop: bool,
    control: bool,
    allow_command: bool,
    allow_acp: bool,
    allow_insecure: bool,
    state: Path | None,
) -> None:
    """Keep an outbound authenticated device connection running until interrupted.

    First connect: --server URL --pair-code CODE [--share DIR].
    Later: --state DIR reuses the device identity and enrollment policy.
    Browser login and device enrollment do not require an OS account password.
    """
    if platform.system() not in {"Windows", "Linux"}:
        raise click.ClickException("Native device connections are supported on Windows and Linux.")
    if control and not desktop:
        raise click.UsageError("--control requires --desktop")
    if allow_acp and (not share or read_only):
        raise click.UsageError("--allow-acp requires a writable --share directory")
    if sum(bool(value) for value in (pair_code, access_key, key_file)) > 1:
        raise click.UsageError("choose --pair-code, --access-key or --key-file")
    state_dir = state or Path.home() / ".octop-device"

    async def run() -> None:
        client = DeviceClient(state_dir)
        saved = client.load_state()
        if saved is not None:
            if any(
                (
                    server,
                    pair_code,
                    access_key,
                    key_file,
                    name,
                    share,
                    read_only,
                    desktop,
                    control,
                    allow_command,
                    allow_acp,
                    allow_insecure,
                )
            ):
                raise DeviceExecutionError(
                    "use --state alone to reconnect; use a separate state directory for new consent"
                )
            executor = client.saved_executor()
            device_id = saved["device_id"]
        else:
            credential = access_key
            if key_file is not None:
                if key_file.stat().st_size > 120:
                    raise DeviceExecutionError("invalid access key file")
                credential = key_file.read_text(encoding="utf-8-sig").strip()
            if not server or not (pair_code or credential):
                raise DeviceExecutionError(
                    "first connect requires --server and --pair-code or --key-file from your account"
                )
            roots = [
                {
                    "id": f"root-{index}",
                    "name": path.name or f"root-{index}",
                    "path": str(path.absolute()),
                    "read": True,
                    "write": not read_only,
                }
                for index, path in enumerate(share, 1)
            ]
            permissions = []
            if roots:
                permissions.append("files_read")
                if not read_only:
                    permissions.append("files_write")
            executor = DeviceExecutor(
                permissions,
                roots,
                state_dir=client.state_dir,
                desktop_enabled=desktop,
                control_enabled=control,
                command_enabled=allow_command,
                acp_enabled=allow_acp,
            )
            enrolled = await client.enroll(
                server,
                pair_code or "",
                name or platform.node(),
                executor,
                allow_insecure=allow_insecure,
                access_key=credential,
            )
            device_id = enrolled["device_id"]
        click.echo(f"Device {device_id}: connecting; keep this client running. Ctrl+C stops it.")
        try:
            await client.run(executor)
        finally:
            await client.stop()
            await executor.close()

    try:
        with DeviceNetwork(state_dir).locked():
            asyncio.run(run())
    except DeviceExecutionError as exc:
        raise click.ClickException(str(exc)) from None
    except (OSError, KeyError, TypeError, ValueError):
        raise click.ClickException(
            "Device connection failed; check the server and private state directory."
        ) from None
    except KeyboardInterrupt:
        click.echo("Device client stopped.")


@device.command("add-controller")
@click.option("--server", required=True, help="Trusted management host HTTPS URL.")
@click.option("--pair-code", help="Single-use code from that host's Devices page.")
@click.option("--access-key", help="Prefer --key-file or the hidden interactive prompt.")
@click.option("--key-file", type=click.Path(exists=True, dir_okay=False, path_type=Path))
@click.option("--name", help="Current device's name shown on that management host.")
@click.option(
    "--share", multiple=True, type=click.Path(exists=True, file_okay=False, path_type=Path)
)
@click.option("--read-only", is_flag=True, help="Disable writes to shared directories.")
@click.option("--desktop", is_flag=True, help="Allow this host to view the desktop.")
@click.option("--control", is_flag=True, help="Allow desktop input; requires --desktop.")
@click.option("--allow-command", is_flag=True, help="Allow confirmed commands under this OS user.")
@click.option(
    "--allow-acp", is_flag=True, help="Run local ACP agents with this OS user's credentials."
)
@click.option("--allow-insecure", is_flag=True, help="Explicitly accept unencrypted remote HTTP.")
@click.option("--state", type=click.Path(file_okay=False, path_type=Path), default=None)
def add_controller(
    server: str,
    pair_code: str | None,
    access_key: str | None,
    key_file: Path | None,
    name: str | None,
    share: tuple[Path, ...],
    read_only: bool,
    desktop: bool,
    control: bool,
    allow_command: bool,
    allow_acp: bool,
    allow_insecure: bool,
    state: Path | None,
) -> None:
    """Enroll another independent management host, without changing existing trust."""
    if platform.system() not in {"Windows", "Linux"}:
        raise click.ClickException("Native device connections are supported on Windows and Linux.")
    if control and not desktop:
        raise click.UsageError("--control requires --desktop")
    if sum(bool(value) for value in (pair_code, access_key, key_file)) > 1:
        raise click.UsageError("choose --pair-code, --access-key or --key-file")
    if allow_command and not share:
        raise click.UsageError("--allow-command requires a shared working directory")
    if allow_acp and (not share or read_only):
        raise click.UsageError("--allow-acp requires a writable shared directory")
    credential = access_key
    try:
        if key_file is not None:
            if key_file.stat().st_size > 120:
                raise DeviceExecutionError("invalid access key file")
            credential = key_file.read_text(encoding="utf-8-sig").strip()
            if not credential:
                raise DeviceExecutionError("empty access key file")
        if not pair_code and not credential:
            credential = click.prompt("Device enrollment key", hide_input=True).strip()
        roots = [
            {
                "id": f"root-{index}",
                "name": path.name or f"root-{index}",
                "path": str(path.absolute()),
                "read": True,
                "write": not read_only,
            }
            for index, path in enumerate(share, 1)
        ]
        permissions = (["files_read"] + ([] if read_only else ["files_write"])) if roots else []
        network = DeviceNetwork(state or Path.home() / ".octop-device")
        added = asyncio.run(
            network.add_controller(
                server,
                pair_code or "",
                name or platform.node(),
                permissions,
                roots,
                desktop_enabled=desktop,
                control_enabled=control,
                command_enabled=allow_command,
                acp_enabled=allow_acp,
                allow_insecure=allow_insecure,
                access_key=credential,
            )
        )
        click.echo(f"Controller {added['id']} saved. Run device run to connect all saved hosts.")
    except DeviceExecutionError as exc:
        raise click.ClickException(str(exc)) from None
    except (OSError, KeyError, TypeError, ValueError):
        raise click.ClickException(
            "Controller setup failed; check its address and private state."
        ) from None


@device.command("controllers")
@click.option("--state", type=click.Path(file_okay=False, path_type=Path), default=None)
def controllers(state: Path | None) -> None:
    """List saved management hosts without exposing credentials or shared paths."""
    try:
        click.echo(json.dumps(DeviceNetwork(state or Path.home() / ".octop-device").controllers()))
    except (OSError, DeviceExecutionError) as exc:
        raise click.ClickException(str(exc)) from None


@device.command("remove-controller")
@click.argument("controller_id")
@click.option("--state", type=click.Path(file_okay=False, path_type=Path), default=None)
def remove_controller(controller_id: str, state: Path | None) -> None:
    """Stop using this local trust profile; preserve private identities and journals."""
    try:
        DeviceNetwork(state or Path.home() / ".octop-device").remove_controller(controller_id)
        click.echo("Local controller trust removed; remote device revocation is separate.")
    except (OSError, DeviceExecutionError) as exc:
        raise click.ClickException(str(exc)) from None


@device.command("run")
@click.option("--state", type=click.Path(file_okay=False, path_type=Path), default=None)
def run_network(state: Path | None) -> None:
    """Restore every saved connection; no fixed management host is required."""
    if platform.system() not in {"Windows", "Linux"}:
        raise click.ClickException("Native device connections are supported on Windows and Linux.")
    try:
        network = DeviceNetwork(state or Path.home() / ".octop-device")
        asyncio.run(
            network.run(lambda profile, status: click.echo(f"Controller {profile}: {status}"))
        )
    except DeviceExecutionError as exc:
        raise click.ClickException(str(exc)) from None
    except (OSError, KeyError, TypeError, ValueError):
        raise click.ClickException(
            "Device network failed; check its private state directory."
        ) from None
    except KeyboardInterrupt:
        click.echo("Device network stopped.")


@device.command("relocate-controller")
@click.argument("controller_id")
@click.option(
    "--from-server",
    required=True,
    help="Current saved endpoint; must match exactly after URL normalization.",
)
@click.option(
    "--server", required=True, help="Trusted new address of the same migrated management instance."
)
@click.option(
    "--allow-insecure",
    is_flag=True,
    help="Explicitly accept HTTP development relocation; cannot downgrade HTTPS to remote HTTP.",
)
@click.option("--state", type=click.Path(file_okay=False, path_type=Path), default=None)
@click.option(
    "--yes",
    is_flag=True,
    help="Confirm the same management instance was migrated and its new address is trusted.",
)
def relocate_controller(
    controller_id: str,
    from_server: str,
    server: str,
    allow_insecure: bool,
    state: Path | None,
    yes: bool,
) -> None:
    """Update a stopped client's endpoint, preserving its identity and local consent.

    Use only after the same management instance's data and credentials have been
    migrated and you have verified the new address is trusted. This is offline;
    no credentials are sent and it does not verify the new host. For a new or
    independent management host, use device add-controller instead.
    """
    try:
        old = validate_relocation_url(from_server)
        new = validate_relocation_url(server)
        click.echo(
            "Confirm the same management instance's data and credentials were migrated and the new address is trusted."
        )
        if not yes:
            click.confirm(f"Relocate controller {controller_id} from {old} to {new}?", abort=True)
        network = DeviceNetwork(state or Path.home() / ".octop-device")
        network.relocate_controller(
            controller_id,
            expected_server=old,
            server_url=new,
            allow_insecure=allow_insecure,
        )
        click.echo(
            f"Controller {controller_id} saved offline at {new}. Restart device run when ready."
        )
    except DeviceExecutionError as exc:
        raise click.ClickException(str(exc)) from None
    except (OSError, KeyError, TypeError, ValueError):
        raise click.ClickException(
            "Controller relocation failed; check its address and private state."
        ) from None


from octop.cli.device_startup_cmd import autostart, join, setup  # noqa: E402

device.add_command(autostart)
device.add_command(setup)
device.add_command(join)
