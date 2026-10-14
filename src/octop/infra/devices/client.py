"""Outbound-only device enrollment and authenticated connection lifecycle."""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import json
import logging
import random
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from octop.infra.devices.executor import (
    DeviceExecutionError,
    DeviceExecutor,
    _reject_links,
    private_state_dir,
    save_private_json,
)
from octop.infra.devices.protocol import CLIENT_PROTOCOL_VERSION, HIGH_RISK_PERMISSIONS


def account_login(
    server_url: str,
    username: str,
    password: str,
    *,
    allow_insecure: bool = False,
    captcha_token: str | None = None,
) -> str:
    """Exchange account password for a short-lived JWT used only for enrollment.

    The JWT must never be written to device-state; only the returned odv_ token is.
    """
    url = validate_server_url(server_url, allow_insecure=allow_insecure)
    body: dict[str, Any] = {"username": username, "password": password}
    if captcha_token:
        body["captcha_token"] = captcha_token
    request = urllib.request.Request(
        f"{url}/api/auth/login",
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(
            self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
        ) -> None:
            return None

    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=20) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise DeviceExecutionError("invalid account login response")
        result = json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise DeviceExecutionError(f"account login rejected (HTTP {exc.code})") from None
    except (OSError, ValueError) as exc:
        raise DeviceExecutionError("control center login unavailable") from exc
    token = result.get("access_token") if isinstance(result, dict) else None
    if not isinstance(token, str) or not token:
        raise DeviceExecutionError("invalid account login response")
    return token


HEARTBEAT_INTERVAL = 20
HEARTBEAT_TIMEOUT = 60


def validate_server_url(server_url: str, *, allow_insecure: bool = False) -> str:
    try:
        parsed = urllib.parse.urlsplit(server_url)
        _port = parsed.port
    except ValueError as exc:
        raise DeviceExecutionError("invalid control center URL") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise DeviceExecutionError("control center URL must be HTTP(S) without credentials")
    loopback = parsed.hostname.lower() == "localhost"
    with contextlib.suppress(ValueError):
        loopback = ipaddress.ip_address(parsed.hostname).is_loopback
    if parsed.scheme == "http" and not loopback and not allow_insecure:
        raise DeviceExecutionError("remote HTTP requires explicit --allow-insecure")
    return server_url.rstrip("/")


def _enroll_http(
    url: str, payload: dict[str, Any], *, authorization: str | None = None
) -> dict[str, Any]:
    headers = {"Content-Type": "application/json"}
    if authorization:
        headers["Authorization"] = authorization
    request = urllib.request.Request(
        f"{url}/api/devices/enroll",
        data=json.dumps(payload).encode("utf-8"),
        headers=headers,
        method="POST",
    )

    # Do not follow redirects: pairing codes must only reach the chosen server.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(
            self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
        ) -> None:
            return None

    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=20) as response:
            raw = response.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            raise DeviceExecutionError("invalid enrollment response")
        result = json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise DeviceExecutionError(f"device enrollment rejected (HTTP {exc.code})") from None
    except (OSError, ValueError) as exc:
        raise DeviceExecutionError("control center enrollment unavailable") from exc
    if not isinstance(result, dict):
        raise DeviceExecutionError("invalid enrollment response")
    return result


class DeviceClient:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = private_state_dir(state_dir)
        self.state_path = self.state_dir / "device.json"
        self._stop = asyncio.Event()
        self._socket: Any = None

    def load_state(self) -> dict[str, Any] | None:
        _reject_links(self.state_path)
        if not self.state_path.exists():
            return None
        try:
            data = json.loads(self.state_path.read_text(encoding="utf-8"))
            if (
                not isinstance(data, dict)
                or not isinstance(data.get("device_id"), str)
                or not isinstance(data.get("device_token"), str)
                or not data["device_token"].startswith("odv_")
                or not isinstance(data.get("policy"), dict)
            ):
                raise ValueError
            validate_server_url(
                data["server_url"], allow_insecure=data.get("allow_insecure") is True
            )
            return data
        except (KeyError, TypeError, ValueError) as exc:
            raise DeviceExecutionError(
                "invalid device state; use a separate state directory to enroll"
            ) from exc

    async def enroll(
        self,
        server_url: str,
        pairing_code: str,
        name: str,
        executor: DeviceExecutor,
        *,
        allow_insecure: bool = False,
        access_key: str | None = None,
        account_token: str | None = None,
    ) -> dict[str, Any]:
        if self.load_state() is not None:
            raise DeviceExecutionError(
                "device is already enrolled; reconnect using its saved state"
            )
        url = validate_server_url(server_url, allow_insecure=allow_insecure)
        provided = sum(bool(value) for value in (pairing_code, access_key, account_token))
        if provided != 1 or not name.strip():
            raise DeviceExecutionError("provide one pairing credential and a device name")
        status = await executor.execute(
            "enrollment-status",
            "status",
            {},
            grant_version=executor.grant_version,
            permissions=list(executor.permissions),
        )
        allowed = sorted(executor.local_permissions & set(executor.capabilities))
        payload: dict[str, Any] = {
            "name": name.strip(),
            "platform": status["platform"],
            "capabilities": executor.capabilities,
            "permissions": allowed,
            "roots": list(executor.local_roots.values()),
        }
        authorization: str | None = None
        if access_key:
            payload["access_key"] = access_key
        elif account_token:
            authorization = f"Bearer {account_token}"
        else:
            payload["pairing_code"] = pairing_code
        loop = asyncio.get_running_loop()
        if authorization:
            response = await loop.run_in_executor(
                None, lambda: _enroll_http(url, payload, authorization=authorization)
            )
        else:
            response = await loop.run_in_executor(None, _enroll_http, url, payload)
        device = response.get("device")
        token = response.get("device_token")
        if (
            not isinstance(device, dict)
            or not isinstance(device.get("device_id"), str)
            or not isinstance(token, str)
            or not token.startswith("odv_")
        ):
            raise DeviceExecutionError("invalid enrollment response")
        # Align local consent with server-applied REQ-007 defaults.
        granted = device.get("permissions")
        if isinstance(granted, list):
            executor.local_permissions |= set(granted) & set(executor.capabilities)
            executor.permissions = set(executor.local_permissions)
        state = {
            "server_url": url,
            "device_id": device["device_id"],
            "device_token": token,
            "allow_insecure": allow_insecure,
            "policy": {
                "permissions": sorted(executor.local_permissions),
                "roots": list(executor.local_roots.values()),
                "desktop_enabled": "desktop_view" in executor.local_permissions,
                "control_enabled": "desktop_control" in executor.local_permissions,
                "command_enabled": "command_exec" in executor.local_permissions,
                "acp_enabled": "acp_run" in executor.local_permissions,
                "remote_grant_mode": "owner_auto",
            },
        }
        save_private_json(self.state_path, state)
        return device

    def saved_executor(self) -> DeviceExecutor:
        state = self.load_state()
        if state is None:
            raise DeviceExecutionError("device is not enrolled")
        policy = state["policy"]
        return DeviceExecutor(
            policy["permissions"],
            policy["roots"],
            state_dir=self.state_dir,
            desktop_enabled=policy.get("desktop_enabled") is True,
            control_enabled=policy.get("control_enabled") is True,
            command_enabled=policy.get("command_enabled") is True,
            acp_enabled=policy.get("acp_enabled") is True,
        )

    async def stop(self) -> None:
        self._stop.set()
        if self._socket is not None:
            await self._socket.close()

    async def run(self, executor: DeviceExecutor) -> None:
        """Reconnect the same identity; never resubmit a disconnected request."""
        import websockets
        from websockets.asyncio.client import connect as WebSocketConnect

        class NoRedirectConnect(WebSocketConnect):
            def process_redirect(self, exc: Exception) -> Exception:
                # A device credential must not follow a control center redirect
                # to a different origin or a less protected transport.
                return DeviceExecutionError("device WebSocket redirects are not allowed")

        state = self.load_state()
        if state is None:
            raise DeviceExecutionError("device is not enrolled")
        base = validate_server_url(
            state["server_url"], allow_insecure=state.get("allow_insecure") is True
        )
        parsed = urllib.parse.urlsplit(base)
        uri = urllib.parse.urlunsplit(
            (
                "wss" if parsed.scheme == "https" else "ws",
                parsed.netloc,
                parsed.path + "/api/devices/connect/ws",
                "",
                "",
            )
        )
        # websockets DEBUG frame logging would expose the hello credential.
        # Use an unregistered, disabled logger regardless of root logging level.
        wire_logger = logging.Logger("octop.device.private_transport")
        wire_logger.disabled = True
        delay = 1.0
        try:
            while not self._stop.is_set():
                try:
                    async with NoRedirectConnect(
                        uri,
                        max_size=4 * 1024 * 1024,
                        max_queue=16,
                        open_timeout=15,
                        close_timeout=5,
                        logger=wire_logger,
                    ) as socket:
                        if self._stop.is_set():
                            return
                        self._socket = socket
                        await socket.send(
                            json.dumps(
                                {
                                    "type": "hello",
                                    "protocol": 1,
                                    "client_protocol_version": CLIENT_PROTOCOL_VERSION,
                                    "device_id": state["device_id"],
                                    "token": state["device_token"],
                                }
                            )
                        )
                        hello = json.loads(await asyncio.wait_for(socket.recv(), 10))
                        if hello.get("type") != "hello_ack" or hello.get("protocol") != 1:
                            raise DeviceExecutionError("device authentication failed")
                        executor.update_grants(
                            hello["grant_version"], hello["permissions"], hello["roots"]
                        )
                        for receipt in executor.reconciliation_results():
                            await socket.send(
                                json.dumps(
                                    {"type": "reconcile", "results": [receipt]}, ensure_ascii=False
                                )
                            )
                        delay = 1.0
                        await self._connected(socket, executor)
                except DeviceExecutionError:
                    raise
                except (
                    OSError,
                    TimeoutError,
                    websockets.exceptions.ConnectionClosed,
                    websockets.exceptions.InvalidHandshake,
                ):
                    pass
                finally:
                    self._socket = None
                    await executor.close()
                if not self._stop.is_set():
                    with contextlib.suppress(TimeoutError):
                        await asyncio.wait_for(
                            self._stop.wait(), delay + random.uniform(0, delay / 4)
                        )
                    delay = min(30.0, delay * 2)
        finally:
            await executor.close()

    async def _connected(self, socket: Any, executor: DeviceExecutor) -> None:
        tasks: dict[str, asyncio.Task[None]] = {}
        last_heartbeat = asyncio.get_running_loop().time()

        async def send_result(frame: dict[str, Any]) -> None:
            operation_id = frame["id"]
            try:
                result = await executor.execute(
                    operation_id,
                    frame["action"],
                    frame["params"],
                    grant_version=frame["grant_version"],
                    permissions=frame["permissions"],
                )
                response = {"type": "result", "id": operation_id, "ok": True, "result": result}
            except asyncio.CancelledError:
                response = {
                    "type": "result",
                    "id": operation_id,
                    "ok": False,
                    "error": "operation cancelled",
                }
            except DeviceExecutionError as exc:
                response = {"type": "result", "id": operation_id, "ok": False, "error": str(exc)}
            finally:
                tasks.pop(operation_id, None)
            with contextlib.suppress(Exception):
                await socket.send(json.dumps(response, ensure_ascii=False))

        async def heartbeat() -> None:
            while True:
                await asyncio.sleep(HEARTBEAT_INTERVAL)
                if asyncio.get_running_loop().time() - last_heartbeat >= HEARTBEAT_TIMEOUT:
                    await socket.close()
                    return
                await socket.send(json.dumps({"type": "heartbeat"}))

        pulse = asyncio.create_task(heartbeat())
        try:
            async for raw in socket:
                try:
                    frame = json.loads(raw)
                    kind = frame["type"]
                except (TypeError, KeyError, ValueError) as exc:
                    raise DeviceExecutionError("invalid device protocol frame") from exc
                if kind == "heartbeat_ack":
                    last_heartbeat = asyncio.get_running_loop().time()
                if kind in {"grants", "heartbeat_ack"} and "grant_version" in frame:
                    if frame["grant_version"] != executor.grant_version:
                        # First stop work accepted under the superseded grant.
                        superseded = list(tasks.values())
                        for task in superseded:
                            task.cancel()
                        await asyncio.gather(*superseded, return_exceptions=True)
                        tasks.clear()
                        await executor.close()
                        executor.update_grants(
                            frame["grant_version"], frame["permissions"], frame["roots"]
                        )
                        executor.abort_uploads()
                elif kind == "grant_proposal":
                    proposal_id = frame.get("proposal_id")
                    desired = frame.get("permissions")
                    roots = frame.get("roots")
                    if (
                        not isinstance(proposal_id, str)
                        or not isinstance(desired, list)
                        or not isinstance(roots, list)
                    ):
                        raise DeviceExecutionError("invalid grant_proposal")
                    high_risk = bool(set(desired) & HIGH_RISK_PERMISSIONS)
                    requires = frame.get("requires_confirm") is True or high_risk
                    decision = "reject"
                    try:
                        if requires:
                            # Interactive CLI confirm for high-risk / confirm mode.
                            import sys

                            label = ",".join(sorted(set(desired)))
                            if sys.stdin is not None and sys.stdin.isatty():
                                answer = (
                                    input(
                                        f"Control center requests permissions [{label}]. Accept? [y/N] "
                                    )
                                    .strip()
                                    .lower()
                                )
                                decision = "accept" if answer in {"y", "yes"} else "reject"
                            else:
                                decision = "reject"
                        else:
                            executor.apply_grant_proposal(desired, roots)
                            decision = "accept"
                    except DeviceExecutionError:
                        decision = "reject"
                    await socket.send(
                        json.dumps(
                            {
                                "type": "grant_resolve",
                                "proposal_id": proposal_id,
                                "decision": decision,
                            },
                            ensure_ascii=False,
                        )
                    )
                elif kind == "desktop_takeover":
                    # 0008 DEC-001: must prompt Allow takeover; never auto-accept (AC-004).
                    request_id = frame.get("request_id")
                    mode = frame.get("mode") or "view"
                    owner_label = frame.get("owner_label") or "owner"
                    if not isinstance(request_id, str):
                        raise DeviceExecutionError("invalid desktop_takeover")
                    decision = "reject"
                    import sys

                    mode_label = "view+control" if mode == "view_control" else "view"
                    if sys.stdin is not None and sys.stdin.isatty():
                        answer = (
                            input(f"Allow desktop takeover by {owner_label} ({mode_label})? [y/N] ")
                            .strip()
                            .lower()
                        )
                        decision = "accept" if answer in {"y", "yes"} else "reject"
                    await socket.send(
                        json.dumps(
                            {
                                "type": "desktop_takeover_resolve",
                                "request_id": request_id,
                                "decision": decision,
                            },
                            ensure_ascii=False,
                        )
                    )
                elif kind == "cancel":
                    operation_id = str(frame.get("id", ""))
                    pending = tasks.get(operation_id)
                    if pending is not None:
                        pending.cancel()
                    await executor.cancel(operation_id)
                    if pending is not None:
                        await asyncio.gather(pending, return_exceptions=True)
                        tasks.pop(operation_id, None)
                elif kind == "request":
                    operation_id = frame.get("id")
                    if (
                        not isinstance(operation_id, str)
                        or not isinstance(frame.get("action"), str)
                        or not isinstance(frame.get("params"), dict)
                        or type(frame.get("grant_version")) is not int
                        or not isinstance(frame.get("permissions"), list)
                    ):
                        raise DeviceExecutionError("invalid device request")
                    if operation_id in tasks:
                        continue  # The original request will send its own result.
                    if len(tasks) >= 8:
                        await socket.send(
                            json.dumps(
                                {
                                    "type": "result",
                                    "id": operation_id,
                                    "ok": False,
                                    "error": "device operation capacity exceeded",
                                }
                            )
                        )
                        continue
                    tasks[operation_id] = asyncio.create_task(send_result(frame))
        finally:
            pulse.cancel()
            for task in list(tasks.values()):
                task.cancel()
            await asyncio.gather(pulse, *list(tasks.values()), return_exceptions=True)
