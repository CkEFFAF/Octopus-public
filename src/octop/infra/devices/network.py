"""Independent outbound connections to explicitly trusted management hosts.

Each host has its own device credential, local consent and executor journal.
The legacy root device.json remains the default connection. This directory is
not an account database and never copies credentials between management hosts.
"""

from __future__ import annotations

import asyncio
import json
import re
import uuid
from collections.abc import Callable, Iterator
from contextlib import contextmanager, suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

from octop.infra.devices.client import DeviceClient, validate_server_url
from octop.infra.devices.executor import (
    DeviceExecutionError,
    DeviceExecutor,
    _reject_links,
    private_state_dir,
    save_private_json,
)
from octop.infra.utils.process_lock import ProcessAlreadyRunning, ProcessLock

MAX_CONTROLLERS = 32
_PROFILE_ID = re.compile(r"^[a-f0-9]{32}$")


def validate_relocation_url(url: str) -> str:
    """Validate a literal endpoint without probing it or accepting HTTP transport.

    Reject characters URL parsers silently strip or browsers reinterpret before
    displaying a confirmation. The relocation itself applies the transport policy.
    """
    if (
        any(
            character.isspace() or ord(character) < 32 or ord(character) == 127 for character in url
        )
        or "\\" in url
    ):
        raise DeviceExecutionError("invalid control center URL")
    return validate_server_url(url, allow_insecure=True)


def _endpoint_key(url: str) -> tuple[str, str, int, str]:
    parsed = urlsplit(url)
    return (
        parsed.scheme.lower(),
        (parsed.hostname or "").lower(),
        parsed.port or (443 if parsed.scheme == "https" else 80),
        parsed.path.rstrip("/"),
    )


class DeviceNetwork:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = private_state_dir(state_dir)
        self.catalog_path = self.state_dir / "network.json"
        self._stop = asyncio.Event()
        self._clients: dict[str, DeviceClient] = {}

    @contextmanager
    def locked(self) -> Iterator[None]:
        """Exclude duplicate clients and edits while saved connections run."""
        _reject_links(self.state_dir)
        try:
            with ProcessLock(self.state_dir / "network.lock"):
                yield
        except ProcessAlreadyRunning as exc:
            raise DeviceExecutionError(
                "this device network is already running; stop it before changing controllers"
            ) from exc

    def _catalog(self) -> dict[str, Any]:
        _reject_links(self.catalog_path)
        if not self.catalog_path.exists():
            return {"version": 1, "controllers": [], "disabled_default": False}
        try:
            if self.catalog_path.stat().st_size > 64 * 1024:
                raise ValueError
            data = json.loads(self.catalog_path.read_text(encoding="utf-8"))
            if (
                not isinstance(data, dict)
                or data.get("version") != 1
                or not isinstance(data.get("controllers"), list)
                or type(data.get("disabled_default", False)) is not bool
                or len(data["controllers"]) > MAX_CONTROLLERS
            ):
                raise ValueError
            seen: set[str] = set()
            for item in data["controllers"]:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("id"), str)
                    or not _PROFILE_ID.fullmatch(item["id"])
                    or item["id"] in seen
                ):
                    raise ValueError
                seen.add(item["id"])
            return data
        except (OSError, ValueError, TypeError) as exc:
            raise DeviceExecutionError(
                "invalid device network catalog; restore its saved file"
            ) from exc

    def _profiles(self) -> list[tuple[str, Path]]:
        catalog = self._catalog()
        result = []
        legacy = self.state_dir / "device.json"
        if legacy.exists() and not catalog.get("disabled_default", False):
            result.append(("default", self.state_dir))
        result.extend(
            (item["id"], self.state_dir / "controllers" / item["id"])
            for item in catalog["controllers"]
        )
        return result

    def controllers(self) -> list[dict[str, Any]]:
        """Return safe connection metadata, never credentials or private roots."""
        result = []
        for profile_id, path in self._profiles():
            try:
                state = DeviceClient(path).load_state()
                if state is None:
                    raise DeviceExecutionError("missing saved identity")
                result.append(
                    {
                        "id": profile_id,
                        "server_url": state["server_url"],
                        "device_id": state["device_id"],
                        "allow_insecure": state.get("allow_insecure") is True,
                        "default": profile_id == "default",
                        "status": "configured",
                    }
                )
            except (OSError, ValueError, KeyError, TypeError):
                result.append(
                    {"id": profile_id, "status": "invalid", "default": profile_id == "default"}
                )
        return result

    async def add_controller(
        self,
        server_url: str,
        pairing_code: str,
        name: str,
        permissions: list[str],
        roots: list[dict[str, Any]],
        *,
        desktop_enabled: bool = False,
        control_enabled: bool = False,
        command_enabled: bool = False,
        allow_insecure: bool = False,
        access_key: str | None = None,
    ) -> dict[str, Any]:
        url = validate_server_url(server_url, allow_insecure=allow_insecure)
        with self.locked():
            catalog = self._catalog()
            profiles = self.controllers()
            if len(profiles) >= MAX_CONTROLLERS:
                raise DeviceExecutionError("device controller limit reached")
            if any(
                item.get("server_url") and _endpoint_key(item["server_url"]) == _endpoint_key(url)
                for item in profiles
            ):
                raise DeviceExecutionError("this management host is already configured")
            profile_id = uuid.uuid4().hex
            client = DeviceClient(self.state_dir / "controllers" / profile_id)
            executor = DeviceExecutor(
                permissions,
                roots,
                state_dir=client.state_dir,
                desktop_enabled=desktop_enabled,
                control_enabled=control_enabled,
                command_enabled=command_enabled,
            )
            try:
                enrolled = await client.enroll(
                    url,
                    pairing_code,
                    name,
                    executor,
                    allow_insecure=allow_insecure,
                    access_key=access_key,
                )
                catalog["controllers"].append({"id": profile_id})
                save_private_json(self.catalog_path, catalog)
                return {"id": profile_id, "server_url": url, "device_id": enrolled["device_id"]}
            finally:
                await executor.close()

    def remove_controller(self, profile_id: str) -> None:
        """Stop using local trust, retaining private journals for reconciliation.

        Removal is offline-only. It does not revoke the device on the remote
        account; that management host can separately revoke its device entry.
        """
        if profile_id != "default" and not _PROFILE_ID.fullmatch(profile_id):
            raise DeviceExecutionError("invalid controller identifier")
        with self.locked():
            catalog = self._catalog()
            if profile_id not in {item["id"] for item in self.controllers()}:
                raise DeviceExecutionError("controller not found")
            if profile_id == "default":
                catalog["disabled_default"] = True
            else:
                catalog["controllers"] = [
                    item for item in catalog["controllers"] if item["id"] != profile_id
                ]
            save_private_json(self.catalog_path, catalog)

    def relocate_controller(
        self,
        profile_id: str,
        *,
        expected_server: str,
        server_url: str,
        allow_insecure: bool = False,
    ) -> dict[str, Any]:
        """Move an existing identity to the same management instance, offline.

        The caller must first verify that the same instance's data and credentials
        were migrated and the new address is trusted. No connection or credential
        is sent by this method. Independent hosts must use add_controller instead.
        Local consent, identity and operation journals remain unchanged.
        """
        if profile_id != "default" and not _PROFILE_ID.fullmatch(profile_id):
            raise DeviceExecutionError("invalid controller identifier")
        with self.locked():
            profiles = dict(self._profiles())
            if profile_id not in profiles:
                raise DeviceExecutionError("controller not found")
            client = DeviceClient(profiles[profile_id])
            state = client.load_state()
            if state is None:
                raise DeviceExecutionError("missing saved identity")
            current = validate_relocation_url(state["server_url"])
            expected = validate_relocation_url(expected_server)
            url = validate_relocation_url(server_url)
            if _endpoint_key(current) != _endpoint_key(expected):
                raise DeviceExecutionError(
                    "--from-server does not match the saved controller endpoint"
                )
            if urlsplit(url).scheme == "http":
                if urlsplit(current).scheme == "https":
                    try:
                        validate_server_url(url)
                    except DeviceExecutionError as exc:
                        raise DeviceExecutionError(
                            "HTTPS cannot be relocated to remote HTTP"
                        ) from exc
                elif not allow_insecure:
                    raise DeviceExecutionError("HTTP relocation requires explicit --allow-insecure")
            validate_server_url(url, allow_insecure=allow_insecure)
            for other_id, path in profiles.items():
                if other_id == profile_id:
                    continue
                other = DeviceClient(path).load_state()
                if other is None:
                    raise DeviceExecutionError("missing saved identity")
                if _endpoint_key(other["server_url"]) == _endpoint_key(url):
                    raise DeviceExecutionError("this management host is already configured")
            save_private_json(
                client.state_path, {**state, "server_url": url, "allow_insecure": allow_insecure}
            )
            return {"id": profile_id, "server_url": url, "device_id": state["device_id"]}

    async def stop(self) -> None:
        self._stop.set()
        await asyncio.gather(
            *(client.stop() for client in self._clients.values()), return_exceptions=True
        )

    async def run(self, on_status: Callable[[str, str], None] | None = None) -> None:
        """Run every saved endpoint; one rejected identity cannot stop the rest."""
        with self.locked():
            profiles = self._profiles()
            if not profiles:
                raise DeviceExecutionError("no trusted controllers; run device setup first")

            async def run_profile(profile_id: str, path: Path) -> None:
                executor: DeviceExecutor | None = None
                try:
                    client = DeviceClient(path)
                    self._clients[profile_id] = client
                    executor = client.saved_executor()
                    if on_status:
                        on_status(profile_id, "connecting")
                    await client.run(executor)
                except Exception:
                    # Invalid/auth-rejected profiles need local attention rather
                    # than repeated enrollment or account credential retries.
                    if on_status:
                        on_status(profile_id, "attention required")
                    await self._stop.wait()
                finally:
                    if executor is not None:
                        with suppress(Exception):
                            await executor.close()
                    self._clients.pop(profile_id, None)

            tasks = [asyncio.create_task(run_profile(*profile)) for profile in profiles]
            try:
                await asyncio.gather(*tasks)
            finally:
                await self.stop()
                for task in tasks:
                    task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
