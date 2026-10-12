"""Account-owned device sessions, authorization and durable operation dispatch."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from octop.infra.auth.access_keys import AccessKeyService
from octop.infra.db.repos.devices import DeviceRow, OperationRow
from octop.infra.db.services import RepoBundle
from octop.infra.devices.protocol import (
    CAPABILITIES,
    CHUNK_SIZE,
    device_error,
    ledger_result,
    result_status,
    validate_action,
)
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.ulid import new_ulid

Send = Callable[[dict[str, Any]], Awaitable[None]]
Close = Callable[[], Awaitable[None]]


@dataclass
class DeviceConnection:
    device_id: str
    connection_id: str
    send: Send
    close: Close


class DeviceService:
    def __init__(self, repos: RepoBundle) -> None:
        self.repos = repos
        self.access_keys = AccessKeyService(repos)
        self._connections: dict[str, DeviceConnection] = {}
        self._pairings: dict[str, tuple[int, float]] = {}
        self._pending: dict[str, tuple[DeviceConnection, asyncio.Future[dict[str, Any]]]] = {}
        self._jobs: dict[str, asyncio.Task[None]] = {}
        self.repos.device_repo.recover_incomplete_operations()

    def replace_repos(self, repos: RepoBundle) -> None:
        if self._connections or self._jobs:
            raise device_error("restart required to replace active device persistence", status=409)
        self.repos = repos
        self.access_keys = AccessKeyService(repos)
        self._pairings.clear()
        repos.device_repo.recover_incomplete_operations()

    def _user(self, owner: int) -> None:
        user = self.repos.user_repo.get(owner)
        if user is None or user.disabled:
            raise OctopError(ErrorCode.FORBIDDEN, "device owner unavailable")

    def pairing(self, owner: int) -> dict[str, Any]:
        self._user(owner)
        now = time.time()
        self._pairings = {k: v for k, v in self._pairings.items() if v[1] > now and v[0] != owner}
        if len(self._pairings) >= 4096:
            raise device_error("pairing capacity reached", status=429)
        code = secrets.token_urlsafe(24)
        expiry = now + 600
        self._pairings[hashlib.sha256(code.encode()).hexdigest()] = (owner, expiry)
        return {"pairing_code": code, "expires_at": expiry}

    def enroll(
        self,
        *,
        pairing_code: str | None = None,
        access_key: str | None = None,
        owner_user_id: int | None = None,
        client_ip: str = "unknown",
        name: str,
        platform: str,
        capabilities: list[str],
        permissions: list[str],
        roots: list[dict[str, Any]],
    ) -> dict[str, Any]:
        # Exactly one enrollment credential: pairing code, access key, or account session.
        provided = sum(bool(value) for value in (pairing_code, access_key, owner_user_id is not None))
        if provided != 1:
            raise OctopError(ErrorCode.AUTH_FAILED, "provide one enrollment credential")
        digest = hashlib.sha256((pairing_code or "").encode()).hexdigest()
        pair = self._pairings.get(digest)
        if access_key:
            owner = int(
                self.access_keys.authenticate(access_key, "devices", client_ip)["owner_user_id"]
            )
        elif owner_user_id is not None:
            owner = int(owner_user_id)
        elif pair is None or pair[1] <= time.time():
            raise OctopError(ErrorCode.AUTH_FAILED, "invalid or expired device pairing")
        else:
            owner = pair[0]
        self._user(owner)
        if not name.strip() or len(name) > 120 or platform not in {"windows", "linux", "darwin"}:
            raise device_error("invalid device identity")
        if not set(capabilities) <= CAPABILITIES or not set(permissions) <= set(capabilities):
            raise device_error("invalid device capabilities")
        if "desktop_control" in permissions and "desktop_view" not in permissions:
            raise device_error("desktop control requires view permission")
        if len(roots) > 20 or len({r["id"] for r in roots}) != len(roots):
            raise device_error("invalid shared roots")
        if pairing_code:
            del self._pairings[digest]
        token = "odv_" + secrets.token_urlsafe(32)
        row = self.repos.device_repo.create(
            new_ulid(),
            owner,
            name.strip(),
            platform,
            sorted(set(capabilities)),
            sorted(set(permissions)),
            roots,
            hashlib.sha256(token.encode()).hexdigest(),
        )
        return {"device": row.public(), "device_token": token}

    def owned(self, owner: int, device_id: str, *, active: bool = True) -> DeviceRow:
        self._user(owner)
        row = self.repos.device_repo.get_for_owner(device_id, owner)
        if row is None:
            raise OctopError(ErrorCode.NOT_FOUND, "device not found")
        if active and row.revoked_at is not None:
            raise OctopError(ErrorCode.FORBIDDEN, "device revoked")
        return row

    def public(self, row: DeviceRow) -> dict[str, Any]:
        return row.public(online=row.device_id in self._connections)

    def list_devices(self, owner: int) -> list[dict[str, Any]]:
        self._user(owner)
        return [self.public(r) for r in self.repos.device_repo.list_for_owner(owner)]

    def authenticate(self, device_id: str, token: str) -> DeviceRow:
        row = self.repos.device_repo.get(device_id)
        if (
            row is None
            or row.revoked_at is not None
            or not token.startswith("odv_")
            or not hmac.compare_digest(row.token_hash, hashlib.sha256(token.encode()).hexdigest())
        ):
            raise OctopError(ErrorCode.AUTH_FAILED, "device authentication failed")
        self._user(row.owner_user_id)
        return row

    def grants(self, row: DeviceRow, *, kind: str = "grants") -> dict[str, Any]:
        return {
            "type": kind,
            "grant_version": row.grant_version,
            "permissions": row.permissions,
            "roots": row.roots,
        }

    async def connect(
        self, device_id: str, token: str, send: Send, close: Close
    ) -> DeviceConnection:
        row = self.authenticate(device_id, token)
        old = self._connections.get(device_id)
        if old is not None:
            self.disconnect(old)
            await old.close()
        # Recheck after awaiting the old close; revocation may have occurred meanwhile.
        row = self.authenticate(device_id, token)
        connection = DeviceConnection(device_id, new_ulid(), send, close)
        self._connections[device_id] = connection
        self.repos.device_repo.touch_seen(device_id)
        try:
            await send(
                {
                    **self.grants(row, kind="hello_ack"),
                    "protocol": 1,
                    "connection_id": connection.connection_id,
                }
            )
        except Exception:
            self.disconnect(connection)
            raise
        return connection

    def disconnect(self, connection: DeviceConnection) -> None:
        if self._connections.get(connection.device_id) is connection:
            self._connections.pop(connection.device_id, None)
        for request_id, (bound, future) in list(self._pending.items()):
            if bound is connection:
                if not future.done():
                    future.set_exception(
                        OctopError(ErrorCode.DEVICE_OFFLINE, "device disconnected")
                    )
                self._pending.pop(request_id, None)

    async def receive(self, connection: DeviceConnection, frame: dict[str, Any]) -> None:
        if self._connections.get(connection.device_id) is not connection:
            raise OctopError(ErrorCode.AUTH_FAILED, "superseded device connection")
        row = self.repos.device_repo.get(connection.device_id)
        if row is None:
            raise OctopError(ErrorCode.AUTH_FAILED, "device unavailable")
        self.owned(row.owner_user_id, row.device_id)
        if frame.get("type") == "heartbeat":
            self.repos.device_repo.touch_seen(row.device_id)
            await connection.send(self.grants(row, kind="heartbeat_ack"))
        elif frame.get("type") == "result":
            self._result(connection, frame)
        elif frame.get("type") == "reconcile":
            receipts = frame.get("results")
            if not isinstance(receipts, list) or len(receipts) > 100:
                raise device_error("invalid reconciliation")
            for receipt in receipts:
                if not isinstance(receipt, dict):
                    raise device_error("invalid receipt")
                op = self.repos.device_repo.get_operation(str(receipt.get("id", "")))
                if (
                    op is None
                    or op.device_id != row.device_id
                    or op.action == "files.transfer"
                    or op.status not in {"queued", "running", "unknown"}
                    or op.grant_version != row.grant_version
                ):
                    continue
                if receipt.get("ok") is True and isinstance(receipt.get("result"), dict):
                    self.repos.device_repo.update_operation(
                        op.operation_id,
                        status=result_status(op.action, receipt["result"]),
                        result=ledger_result(op.action, receipt["result"]),
                    )
                else:
                    self.repos.device_repo.update_operation(
                        op.operation_id,
                        status="unknown",
                        error="unconfirmed device outcome",
                    )
        else:
            raise device_error("invalid device frame")

    def _result(self, connection: DeviceConnection, frame: dict[str, Any]) -> None:
        pending = self._pending.get(str(frame.get("id", "")))
        if pending is None or pending[0] is not connection or pending[1].done():
            return
        future = pending[1]
        if frame.get("ok") is True and isinstance(frame.get("result"), dict):
            future.set_result(frame["result"])
        else:
            future.set_exception(
                device_error(str(frame.get("error", "device operation failed"))[:500])
            )

    async def update(
        self,
        owner: int,
        device_id: str,
        *,
        name: str | None = None,
        permissions: list[str] | None = None,
    ) -> dict[str, Any]:
        row = self.owned(owner, device_id)
        # UI changes may reduce current grants, never enlarge the local consent.
        if permissions is not None and not set(permissions) <= set(row.permissions):
            raise OctopError(
                ErrorCode.FORBIDDEN, "increasing device permission requires re-enrollment"
            )
        if (
            permissions is not None
            and "desktop_control" in permissions
            and "desktop_view" not in permissions
        ):
            raise device_error("desktop control requires view permission")
        updated = self.repos.device_repo.update(device_id, name=name, permissions=permissions)
        assert updated is not None
        connection = self._connections.get(device_id)
        if permissions is not None:
            await self._interrupt_device(device_id)
            if connection is not None:
                with contextlib.suppress(Exception):
                    await connection.send(self.grants(updated))
        return self.public(updated)

    async def revoke(self, owner: int, device_id: str) -> dict[str, Any]:
        self.owned(owner, device_id, active=False)
        row = self.repos.device_repo.revoke(device_id)
        assert row is not None
        await self._interrupt_device(device_id)
        connection = self._connections.get(device_id)
        if connection is not None:
            self.disconnect(connection)
            await connection.close()
        return self.public(row)

    async def _interrupt_device(self, device_id: str) -> None:
        for request_id, (connection, future) in list(self._pending.items()):
            if connection.device_id != device_id:
                continue
            if not future.done():
                future.set_exception(OctopError(ErrorCode.FORBIDDEN, "device permission changed"))
            with contextlib.suppress(Exception):
                await connection.send({"type": "cancel", "id": request_id})
        for op_id, task in list(self._jobs.items()):
            op = self.repos.device_repo.get_operation(op_id)
            if op and (op.device_id == device_id or op.params.get("source_device_id") == device_id):
                task.cancel()
                self.repos.device_repo.update_operation(
                    op_id,
                    status="cancelled",
                    error="device permission changed",
                    expected_statuses=("queued",),
                )
        # Pending confirmations must not remain usable after grant changes.
        row = self.repos.device_repo.get(device_id)
        if row:
            for op in self.repos.device_repo.list_operations(
                row.owner_user_id, device_id=device_id
            ):
                if op.status == "pending_confirmation":
                    self.repos.device_repo.update_operation(
                        op.operation_id, status="cancelled", error="device permission changed"
                    )

    def authorize(
        self,
        owner: int,
        device_id: str,
        action: str,
        params: dict[str, Any],
        *,
        agent_id: str | None = None,
    ) -> DeviceRow:
        row = self.owned(owner, device_id)
        required = validate_action(action, params)
        if required and (required not in row.permissions or required not in row.capabilities):
            raise OctopError(ErrorCode.FORBIDDEN, "device capability not granted")
        if agent_id:
            agent = self.repos.agent_repo.get(agent_id)
            if agent is None or agent.user_id != owner:
                raise OctopError(ErrorCode.FORBIDDEN, "agent cannot use this device")
        if device_id not in self._connections:
            raise OctopError(ErrorCode.DEVICE_OFFLINE, "device offline")
        if (
            action.startswith("files.")
            and action in {"files.list", "files.stat", "files.read", "files.write_begin"}
            or action == "command.run"
            or action == "acp.open"
        ):
            root = next((r for r in row.roots if r["id"] == params.get("root_id")), None)
            read = action in {"files.list", "files.stat", "files.read"}
            if root is None or (
                action != "command.run" and not root.get("read" if read else "write")
            ):
                raise OctopError(ErrorCode.FORBIDDEN, "shared directory not granted")
            if action == "acp.open" and not root.get("read"):
                raise OctopError(ErrorCode.FORBIDDEN, "ACP requires a readable shared root")
        return row

    async def call(
        self,
        owner: int,
        device_id: str,
        action: str,
        params: dict[str, Any],
        *,
        request_id: str | None = None,
        agent_id: str | None = None,
        expected_version: int | None = None,
        allow_command: bool = False,
        allow_acp: bool = False,
    ) -> dict[str, Any]:
        if action == "command.run" and not allow_command:
            raise OctopError(ErrorCode.FORBIDDEN, "command requires human confirmation")
        if action.startswith("acp.") and not allow_acp:
            raise OctopError(ErrorCode.FORBIDDEN, "ACP calls require an expert device binding")
        row = self.authorize(owner, device_id, action, params, agent_id=agent_id)
        if len(self._pending) >= 128:
            raise device_error("device operation capacity reached", status=429)
        if expected_version is not None and row.grant_version != expected_version:
            raise OctopError(ErrorCode.FORBIDDEN, "device permission changed")
        connection = self._connections[device_id]
        audit = request_id is None and action in {
            "desktop.input",
            "files.write_begin",
            "files.write_commit",
            "files.write_abort",
            "acp.open",
            "acp.close",
        }
        request_id = request_id or new_ulid()
        if audit:
            audit_params = (
                {"root_id": params.get("root_id"), "runner": params.get("runner")}
                if action == "acp.open"
                else {}
                if action == "acp.close"
                else {
                    key: value for key, value in params.items() if key not in {"text", "data_b64"}
                }
            )
            self.repos.device_repo.create_operation(
                request_id,
                device_id,
                owner,
                action,
                audit_params,
                agent_id=agent_id,
                grant_version=row.grant_version,
                status="running",
            )
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = (connection, future)
        try:
            await connection.send(
                {
                    "type": "request",
                    "id": request_id,
                    "action": action,
                    "params": params,
                    "grant_version": row.grant_version,
                    "permissions": row.permissions,
                }
            )
            # Allow the device's own deadline plus process cleanup and delivery.
            wait_timeout = int(params.get("timeout", 60)) + 15 if action == "command.run" else 30
            result = await asyncio.wait_for(future, wait_timeout)
            if audit:
                self.repos.device_repo.update_operation(
                    request_id, status="completed", result=ledger_result(action, result)
                )
            return result
        except (TimeoutError, OSError, asyncio.CancelledError) as exc:
            if audit:
                self.repos.device_repo.update_operation(
                    request_id, status="unknown", error="unconfirmed device outcome"
                )
            with contextlib.suppress(Exception):
                await connection.send({"type": "cancel", "id": request_id})
            if not isinstance(exc, asyncio.CancelledError):
                raise OctopError(
                    ErrorCode.DEVICE_OFFLINE, "device did not confirm the outcome"
                ) from exc
            raise
        except OctopError as exc:
            if audit:
                self.repos.device_repo.update_operation(
                    request_id,
                    status="unknown"
                    if exc.code in {ErrorCode.DEVICE_OFFLINE, ErrorCode.FORBIDDEN}
                    else "failed",
                    error=str(exc)[:500],
                )
            raise
        except Exception:
            if audit:
                self.repos.device_repo.update_operation(
                    request_id, status="unknown", error="unconfirmed device outcome"
                )
            raise
        finally:
            self._pending.pop(request_id, None)
            if not future.done():
                future.cancel()

    def operation(self, owner: int, operation_id: str) -> OperationRow:
        self._user(owner)
        op = self.repos.device_repo.get_operation(operation_id, owner)
        if op is None:
            raise OctopError(ErrorCode.NOT_FOUND, "operation not found")
        return op

    def submit(
        self,
        owner: int,
        device_id: str,
        action: str,
        params: dict[str, Any],
        *,
        agent_id: str | None = None,
        task_run_id: str | None = None,
    ) -> dict[str, Any]:
        if action.startswith("acp."):
            raise OctopError(ErrorCode.FORBIDDEN, "ACP streams cannot be submitted as operations")
        if len(self._jobs) >= 32:
            raise device_error("device operation capacity reached", status=429)
        row = self.authorize(owner, device_id, action, params, agent_id=agent_id)
        op = self.repos.device_repo.create_operation(
            new_ulid(),
            device_id,
            owner,
            action,
            params,
            agent_id=agent_id,
            task_run_id=task_run_id,
            grant_version=row.grant_version,
            status="pending_confirmation" if action == "command.run" else "queued",
        )
        if op.status == "queued":
            self._launch(op)
        return op.public()

    def _launch(self, op: OperationRow) -> None:
        task = asyncio.create_task(self._execute(op), name=f"device-op-{op.operation_id}")
        self._jobs[op.operation_id] = task
        task.add_done_callback(lambda _: self._jobs.pop(op.operation_id, None))

    async def _execute(self, op: OperationRow) -> None:
        started = self.repos.device_repo.update_operation(
            op.operation_id, status="running", expected_statuses=("queued",)
        )
        if started is None or started.status != "running":
            return
        try:
            if op.action == "files.transfer":
                value = await self._transfer(op)
            else:
                value = await self.call(
                    op.owner_user_id,
                    op.device_id,
                    op.action,
                    op.params,
                    request_id=op.operation_id,
                    agent_id=op.agent_id,
                    expected_version=op.grant_version,
                    allow_command=True,
                )
            self.repos.device_repo.update_operation(
                op.operation_id,
                status=result_status(op.action, value),
                result=ledger_result(op.action, value),
                expected_statuses=("running", "unknown"),
            )
        except asyncio.CancelledError:
            self.repos.device_repo.update_operation(
                op.operation_id,
                status="unknown",
                error="cancel requested; outcome unconfirmed",
                expected_statuses=("queued", "running", "unknown"),
            )
        except Exception as exc:
            unknown = (
                isinstance(exc, (TimeoutError, OSError))
                or isinstance(exc, OctopError)
                and exc.code in {ErrorCode.DEVICE_OFFLINE, ErrorCode.FORBIDDEN}
            )
            self.repos.device_repo.update_operation(
                op.operation_id,
                status="unknown" if unknown else "failed",
                error=str(exc)[:500]
                if isinstance(exc, OctopError)
                else "unconfirmed device outcome",
                expected_statuses=("queued", "running", "unknown"),
            )

    def confirm(self, owner: int, operation_id: str) -> dict[str, Any]:
        op = self.operation(owner, operation_id)
        if op.status != "pending_confirmation":
            raise device_error("operation no longer awaits confirmation", status=409)
        row = self.authorize(owner, op.device_id, op.action, op.params, agent_id=op.agent_id)
        if row.grant_version != op.grant_version:
            raise OctopError(ErrorCode.FORBIDDEN, "device permission changed")
        if len(self._jobs) >= 32:
            raise device_error("device operation capacity reached", status=429)
        updated = self.repos.device_repo.update_operation(operation_id, status="queued")
        assert updated is not None
        self._launch(updated)
        return updated.public()

    async def cancel(self, owner: int, operation_id: str) -> dict[str, Any]:
        op = self.operation(owner, operation_id)
        if op.status in {"completed", "failed", "cancelled", "unknown"}:
            return op.public()
        task = self._jobs.get(operation_id)
        if task:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            self.repos.device_repo.update_operation(
                operation_id, status="cancelled", expected_statuses=("queued",)
            )
        else:
            self.repos.device_repo.update_operation(operation_id, status="cancelled")
        return self.operation(owner, operation_id).public()

    def transfer(
        self,
        owner: int,
        params: dict[str, Any],
        *,
        agent_id: str | None = None,
        task_run_id: str | None = None,
    ) -> dict[str, Any]:
        if len(self._jobs) >= 32:
            raise device_error("device operation capacity reached", status=429)
        source_id = str(params["source_device_id"])
        target_id = str(params["target_device_id"])
        source = self.authorize(
            owner, source_id, "files.read", {"root_id": params["source_root_id"]}, agent_id=agent_id
        )
        target = self.authorize(
            owner,
            target_id,
            "files.write_begin",
            {"root_id": params["target_root_id"]},
            agent_id=agent_id,
        )
        clean = {**params, "source_grant_version": source.grant_version}
        op = self.repos.device_repo.create_operation(
            new_ulid(),
            target_id,
            owner,
            "files.transfer",
            clean,
            agent_id=agent_id,
            task_run_id=task_run_id,
            grant_version=target.grant_version,
        )
        self._launch(op)
        return op.public()

    async def wait_for_task_run(self, owner: int, task_run_id: str) -> None:
        """Agent narration cannot complete a task while its device work is unresolved."""
        while True:
            operations = self.repos.device_repo.list_for_task_run(owner, task_run_id)
            if any(op.status in {"failed", "cancelled", "unknown"} for op in operations):
                raise device_error("task device operation failed or has an unconfirmed outcome")
            if all(op.status == "completed" for op in operations):
                return
            await asyncio.sleep(1)

    async def cancel_task_run(self, owner: int, task_run_id: str) -> None:
        for op in self.repos.device_repo.list_for_task_run(owner, task_run_id):
            await self.cancel(owner, op.operation_id)

    async def _transfer(self, op: OperationRow) -> dict[str, Any]:
        p = op.params
        source_id = str(p["source_device_id"])
        source_version = int(p["source_grant_version"])

        async def source(action: str, params: dict[str, Any]) -> dict[str, Any]:
            return await self.call(
                op.owner_user_id,
                source_id,
                action,
                params,
                expected_version=source_version,
                agent_id=op.agent_id,
            )

        async def target(action: str, params: dict[str, Any]) -> dict[str, Any]:
            return await self.call(
                op.owner_user_id,
                op.device_id,
                action,
                params,
                expected_version=op.grant_version,
                agent_id=op.agent_id,
            )

        info = await source(
            "files.stat", {"root_id": p["source_root_id"], "path": p["source_path"]}
        )
        size = int(info["size"])
        if info.get("is_dir") or not 0 <= size <= 1024**4:
            raise device_error("invalid source file")
        begin = await target(
            "files.write_begin",
            {
                "root_id": p["target_root_id"],
                "path": p["target_path"],
                "size": size,
                "sha256": info["sha256"],
            },
        )
        upload_id = str(begin["upload_id"])
        transferred = 0
        digest = hashlib.sha256()
        try:
            while transferred < size:
                chunk = await source(
                    "files.read",
                    {
                        "root_id": p["source_root_id"],
                        "path": p["source_path"],
                        "offset": transferred,
                        "length": min(CHUNK_SIZE, size - transferred),
                    },
                )
                data = base64.b64decode(chunk["data_b64"], validate=True)
                if not data or len(data) > min(CHUNK_SIZE, size - transferred):
                    raise device_error("source file changed during transfer")
                digest.update(data)
                ack = await target(
                    "files.write_chunk",
                    {"upload_id": upload_id, "offset": transferred, "data_b64": chunk["data_b64"]},
                )
                transferred += len(data)
                if ack.get("bytes_done") != transferred:
                    raise device_error("invalid transfer acknowledgement")
                self.repos.device_repo.update_operation(
                    op.operation_id,
                    status="running",
                    result={"bytes_total": size, "bytes_done": transferred},
                )
            if digest.hexdigest() != info["sha256"]:
                raise device_error("source checksum changed")
            result = await target("files.write_commit", {"upload_id": upload_id})
            if result.get("sha256") != digest.hexdigest() or result.get("size") != size:
                raise device_error("target checksum mismatch")
            return {**result, "bytes_total": size, "bytes_done": size}
        finally:
            with contextlib.suppress(Exception):
                await target("files.write_abort", {"upload_id": upload_id})

    async def shutdown(self) -> None:
        for task in list(self._jobs.values()):
            task.cancel()
        await asyncio.gather(*list(self._jobs.values()), return_exceptions=True)
        for connection in list(self._connections.values()):
            self.disconnect(connection)
            with contextlib.suppress(Exception):
                await connection.close()
        self._pairings.clear()
