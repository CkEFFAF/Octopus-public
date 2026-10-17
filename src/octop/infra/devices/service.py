"""Account-owned device sessions, authorization and durable operation dispatch."""

from __future__ import annotations

import asyncio
import base64
import contextlib
import hashlib
import hmac
import json
import secrets
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from octop.infra.auth.access_keys import AccessKeyService
from octop.infra.db.repos.devices import DeviceRow, OperationRow
from octop.infra.db.services import RepoBundle
from octop.infra.devices.protocol import (
    CAPABILITIES,
    CHUNK_SIZE,
    CLIENT_PROTOCOL_VERSION,
    DEFAULT_REMOTE_GRANT_MODE,
    DESKTOP_TAKEOVER_MODES,
    GRANT_PROTOCOL_VERSION,
    HIGH_RISK_PERMISSIONS,
    PENDING_GRANT_TTL_SECONDS,
    PENDING_TAKEOVER_TTL_SECONDS,
    REMOTE_GRANT_MODES,
    TRUST_MODES,
    device_error,
    ledger_result,
    merge_enroll_permissions,
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
    root_candidates: list[dict[str, Any]] | None = None


class DeviceService:
    def __init__(self, repos: RepoBundle, *, local_state_dir: Path | None = None) -> None:
        self.repos = repos
        from octop.infra.execution.targets import LocalExecutionBackend

        self.local_execution = (
            LocalExecutionBackend(local_state_dir, self) if local_state_dir else None
        )
        self.access_keys = AccessKeyService(repos)
        controller_id = repos.settings_repo.get("execution.controller_id")
        if controller_id is None:
            controller_id = new_ulid()
            repos.settings_repo.set("execution.controller_id", controller_id)
        self.controller_id = controller_id
        self._connections: dict[str, DeviceConnection] = {}
        self._pairings: dict[str, tuple[int, float]] = {}
        self._pending: dict[str, tuple[DeviceConnection, asyncio.Future[dict[str, Any]]]] = {}
        self._jobs: dict[str, asyncio.Task[None]] = {}
        # proposal_id -> payload; in-memory MVP (DEC-002 TTL enforced on read)
        self._proposals: dict[str, dict[str, Any]] = {}
        self._client_protocol: dict[str, int] = {}
        # 0008 MVP-S1: owner -> current desktop target device_id (cold standby)
        self._desktop_targets: dict[int, str] = {}
        # request_id -> takeover payload (TTL PENDING_TAKEOVER_TTL_SECONDS)
        self._takeovers: dict[str, dict[str, Any]] = {}
        # bounded audit trail for switch/reject/timeout (AC-011)
        self._takeover_events: list[dict[str, Any]] = []
        self.repos.device_repo.recover_incomplete_operations()

    def replace_repos(self, repos: RepoBundle) -> None:
        if (
            self._connections
            or self._jobs
            or (self.local_execution and self.local_execution.active)
        ):
            raise device_error("restart required to replace active device persistence", status=409)
        self.repos = repos
        self.access_keys = AccessKeyService(repos)
        self._pairings.clear()
        controller_id = repos.settings_repo.get("execution.controller_id")
        if controller_id is None:
            controller_id = new_ulid()
            repos.settings_repo.set("execution.controller_id", controller_id)
        self.controller_id = controller_id
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
        trust_mode: str = "restricted",
    ) -> dict[str, Any]:
        # Exactly one enrollment credential: pairing code, access key, or account session.
        provided = sum(
            bool(value) for value in (pairing_code, access_key, owner_user_id is not None)
        )
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
        # REQ-007: force-include default grants that the client can support.
        effective_permissions = merge_enroll_permissions(capabilities, permissions)
        if trust_mode not in TRUST_MODES:
            raise device_error("invalid device trust mode")
        if trust_mode == "owner":
            effective_permissions = sorted(set(capabilities))
        if (
            "desktop_control" in effective_permissions
            and "desktop_view" not in effective_permissions
        ):
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
            effective_permissions,
            roots,
            hashlib.sha256(token.encode()).hexdigest(),
        )
        if trust_mode == "owner":
            row = self.repos.device_repo.set_policy(
                row.device_id,
                trust_mode="owner",
                permissions=effective_permissions,
                working_dir=None,
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
        payload = row.public(online=row.device_id in self._connections)
        pending = self._pending_for(row.device_id)
        if pending is not None:
            payload["pending_proposal"] = pending
        return payload

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
            "remote_grant_mode": row.remote_grant_mode,
            "trust_mode": row.trust_mode,
            "policy_revision": row.policy_revision,
            "working_dir": row.working_dir,
            "controller_id": self.controller_id,
        }

    def owner_trusted(self, row: DeviceRow) -> bool:
        return (
            row.trust_mode == row.applied_trust_mode == "owner"
            and row.policy_revision == row.applied_policy_revision
            and self._client_protocol.get(row.device_id, 1) >= CLIENT_PROTOCOL_VERSION
        )

    async def set_policy(
        self,
        owner: int,
        device_id: str,
        *,
        trust_mode: str,
        permissions: list[str] | None = None,
        working_dir: str | None = None,
    ) -> dict[str, Any]:
        row = self.owned(owner, device_id)
        if trust_mode not in TRUST_MODES:
            raise device_error("invalid device trust mode")
        if (
            device_id in self._connections
            and self._client_protocol[device_id] < CLIENT_PROTOCOL_VERSION
        ):
            raise device_error("CLIENT_OUTDATED: upgrade to device protocol v3", status=409)
        desired = sorted(set(row.capabilities if permissions is None else permissions))
        if not set(desired) <= set(row.capabilities):
            raise device_error("device capability unavailable")
        if "desktop_control" in desired and "desktop_view" not in desired:
            raise device_error("desktop control requires view permission")
        if working_dir is not None and (not working_dir.strip() or "\x00" in working_dir):
            raise device_error("invalid working directory")
        row = self.repos.device_repo.set_policy(
            device_id, trust_mode=trust_mode, permissions=desired, working_dir=working_dir
        )
        connection = self._connections.get(device_id)
        if connection is not None:
            await connection.send(self.grants(row))
        return self.public(self.owned(owner, device_id))

    def _purge_proposals(self) -> None:
        now = time.time()
        expired = [
            pid for pid, item in self._proposals.items() if float(item.get("expires_at", 0)) <= now
        ]
        for pid in expired:
            self._proposals.pop(pid, None)

    def _pending_for(self, device_id: str) -> dict[str, Any] | None:
        self._purge_proposals()
        for item in self._proposals.values():
            if item.get("device_id") == device_id and item.get("status") == "pending":
                return {
                    "proposal_id": item["proposal_id"],
                    "permissions": item["permissions"],
                    "roots": item["roots"],
                    "requires_confirm": item["requires_confirm"],
                    "expires_at": item["expires_at"],
                }
        return None

    def grant_status(self, owner: int, device_id: str) -> dict[str, Any]:
        row = self.owned(owner, device_id, active=False)
        return {
            "grant_version": row.grant_version,
            "permissions": row.permissions,
            "roots": row.roots,
            "remote_grant_mode": row.remote_grant_mode,
            "pending_proposal": self._pending_for(device_id),
            "client_protocol_version": self._client_protocol.get(device_id),
            "online": device_id in self._connections and row.revoked_at is None,
        }

    async def connect(
        self,
        device_id: str,
        token: str,
        send: Send,
        close: Close,
        *,
        client_protocol_version: int = 1,
        software_version: str | None = None,
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
        self._client_protocol[device_id] = (
            int(client_protocol_version) if isinstance(client_protocol_version, int) else 1
        )
        self.repos.device_repo.touch_seen(device_id)
        # DEC-002: persist software_version on hello/connect, not only heartbeat.
        if isinstance(software_version, str) and software_version.strip():
            self.repos.device_repo.set_software_version(device_id, software_version.strip())
        try:
            await send(
                {
                    **self.grants(row, kind="hello_ack"),
                    "protocol": 1,
                    "connection_id": connection.connection_id,
                    "client_protocol_version": self._client_protocol[device_id],
                }
            )
            pending = self._pending_for(device_id)
            if pending is not None and self._client_protocol[device_id] >= GRANT_PROTOCOL_VERSION:
                await send(
                    {
                        "type": "grant_proposal",
                        "proposal_id": pending["proposal_id"],
                        "grant_version": row.grant_version,
                        "permissions": pending["permissions"],
                        "roots": pending["roots"],
                        "requires_confirm": pending["requires_confirm"],
                        "expires_at": pending["expires_at"],
                    }
                )
        except Exception:
            self.disconnect(connection)
            raise
        return connection

    async def _maybe_send_update_offer(self, connection: DeviceConnection, row: DeviceRow) -> None:
        """Push device_update.offer on heartbeat when Hub policy targets this device."""
        try:
            from octop.infra.devices.protocol import device_update_offer_frame
            from octop.infra.devices.update_policy import (
                build_offer,
                load_policy_from_settings,
            )

            policy = load_policy_from_settings(self.repos.settings_repo.get)
            offer = build_offer(
                policy,
                device_id=row.device_id,
                platform=row.platform,
            )
            if offer is None:
                return
            await connection.send(device_update_offer_frame(offer))
        except Exception:
            import logging

            logging.getLogger(__name__).debug("device update offer skipped", exc_info=True)

    def disconnect(self, connection: DeviceConnection) -> None:
        if self._connections.get(connection.device_id) is connection:
            self._connections.pop(connection.device_id, None)
            self._client_protocol.pop(connection.device_id, None)
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
            sw = frame.get("software_version")
            if isinstance(sw, str) and sw.strip():
                self.repos.device_repo.set_software_version(row.device_id, sw.strip())
                row = self.repos.device_repo.get(row.device_id) or row
            await connection.send(self.grants(row, kind="heartbeat_ack"))
            await self._maybe_send_update_offer(connection, row)
        elif frame.get("type") == "device_update.report":
            from octop.infra.devices.protocol import validate_update_report

            report = validate_update_report(frame)
            self.repos.device_repo.set_update_report(
                row.device_id,
                status=report["status"],
                software_version=report.get("software_version"),
                error=report.get("error"),
                stage_version=report.get("stage_version"),
            )
        elif frame.get("type") == "policy_rejected":
            revision, error = frame.get("policy_revision"), frame.get("error")
            if (
                type(revision) is not int
                or revision != row.policy_revision
                or not isinstance(error, str)
            ):
                raise device_error("invalid device policy rejection")
            self.repos.device_repo.policy_failed(row.device_id, revision, error)
        elif frame.get("type") == "policy_applied":
            revision, mode, metadata = (
                frame.get("policy_revision"),
                frame.get("trust_mode"),
                frame.get("runtime"),
            )
            if (
                self._client_protocol[row.device_id] < CLIENT_PROTOCOL_VERSION
                or type(revision) is not int
                or revision != row.policy_revision
                or mode != row.trust_mode
                or not isinstance(metadata, dict)
            ):
                raise device_error("invalid device policy acknowledgement")
            safe = {
                key: metadata[key]
                for key in (
                    "os_user",
                    "working_dir",
                    "hostname",
                    "client_protocol_version",
                    "job_protocol_version",
                    "workbench_protocol_version",
                    "terminal_protocol_version",
                    "capability_protocol_version",
                    "browser_protocol_version",
                    "desktop_protocol_version",
                    "transfer_protocol_version",
                )
                if key in metadata
            }
            if any(not isinstance(value, (str, int)) for value in safe.values()):
                raise device_error("invalid device runtime metadata")
            self.repos.device_repo.report_policy(
                row.device_id, revision=revision, trust_mode=mode, metadata=safe
            )
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
                self._record_execution_receipt(op.operation_id, op.owner_user_id)
        elif frame.get("type") == "grant_resolve":
            proposal_id = frame.get("proposal_id")
            decision = frame.get("decision")
            if not isinstance(proposal_id, str) or decision not in {"accept", "reject"}:
                raise device_error("invalid grant_resolve")
            await self.resolve_grant_proposal(
                row.device_id, proposal_id, accept=(decision == "accept")
            )
        elif frame.get("type") == "desktop_takeover_resolve":
            request_id = frame.get("request_id")
            decision = frame.get("decision")
            if not isinstance(request_id, str) or decision not in {"accept", "reject"}:
                raise device_error("invalid desktop_takeover_resolve")
            await self.resolve_desktop_takeover(
                row.device_id, request_id, accept=(decision == "accept")
            )
        elif frame.get("type") == "root_candidates":
            candidates = frame.get("candidates")
            if not isinstance(candidates, list) or len(candidates) > 50:
                raise device_error("invalid root_candidates")
            connection.root_candidates = candidates
        else:
            raise device_error("invalid device frame")

    def _result(self, connection: DeviceConnection, frame: dict[str, Any]) -> None:
        pending = self._pending.get(str(frame.get("id", "")))
        if pending is None:
            op = self.repos.device_repo.get_operation(str(frame.get("id", "")))
            row = self.repos.device_repo.get(connection.device_id)
            if (
                op
                and row
                and op.device_id == connection.device_id
                and op.grant_version == row.grant_version
                and op.status == "unknown"
                and frame.get("ok") is True
                and isinstance(frame.get("result"), dict)
            ):
                self.repos.device_repo.update_operation(
                    op.operation_id,
                    status=result_status(op.action, frame["result"]),
                    result=ledger_result(op.action, frame["result"]),
                    expected_statuses=("unknown",),
                )
                self._record_execution_receipt(op.operation_id, op.owner_user_id)
            return
        if pending is None or pending[0] is not connection or pending[1].done():
            return
        future = pending[1]
        if frame.get("ok") is True and isinstance(frame.get("result"), dict):
            future.set_result(frame["result"])
        else:
            future.set_exception(
                device_error(str(frame.get("error", "device operation failed"))[:500])
            )

    def set_capability_policy(
        self,
        owner: int,
        device_id: str,
        policy: dict[str, Any] | None,
        *,
        actor: str | None = None,
        schedule_agent_reload: bool = True,
    ) -> dict[str, Any]:
        """Persist devices.capability_policy_json (0025 S0). Next turn picks it up."""
        from octop.infra.devices.capability_policy import (
            dump_capability_policy,
            policy_missing_mcp,
            validate_capability_policy_shape,
        )

        row = self.owned(owner, device_id)
        normalized = validate_capability_policy_shape(policy)
        stored = dump_capability_policy(normalized)
        before = dump_capability_policy(row.capability_policy)
        updated = self.repos.device_repo.update(device_id, capability_policy_json=stored)
        assert updated is not None
        active_names = self._active_mcp_names_for_owner(owner)
        missing = policy_missing_mcp(normalized, active_names)
        self.repos.audit_repo.write(
            actor=actor or str(owner),
            action="device.capability_policy.update",
            target=device_id,
            payload=json.dumps(
                {
                    "before": before,
                    "after": stored,
                    "missing_or_unauthorized": missing,
                },
                ensure_ascii=False,
            ),
        )
        reload_status = {"reload_status": "scheduled"}
        if schedule_agent_reload:
            reload_status = self._schedule_reload_for_device_binding(owner, device_id)
        public = self.public(updated)
        public["missing_or_unauthorized"] = missing
        public["reload_status"] = reload_status.get("reload_status", "scheduled")
        public["effective_next_turn"] = True
        return public

    def capability_policy_alerts(self, owner: int, device_id: str) -> dict[str, Any]:
        """Return missing MCP names referenced by the device pack."""
        from octop.infra.devices.capability_policy import (
            dump_capability_policy,
            parse_capability_policy,
            policy_missing_mcp,
        )

        row = self.owned(owner, device_id)
        policy = parse_capability_policy(row.capability_policy)
        missing = policy_missing_mcp(policy, self._active_mcp_names_for_owner(owner))
        return {
            "device_id": device_id,
            "capability_policy": policy if dump_capability_policy(policy) else None,
            "missing_or_unauthorized": missing,
        }

    def seed_capability_mcp(
        self,
        owner: int,
        device_id: str,
        mcp_servers: list[str],
        *,
        actor: str | None = None,
    ) -> dict[str, Any]:
        """Idempotent ops seed into the device pack (does not rewrite expert lists)."""
        from octop.infra.devices.capability_policy import seed_mcp_into_policy

        row = self.owned(owner, device_id)
        seeded = seed_mcp_into_policy(row.capability_policy, mcp_servers=mcp_servers)
        return self.set_capability_policy(owner, device_id, seeded, actor=actor or str(owner))

    def _active_mcp_names_for_owner(self, owner: int) -> set[str]:
        try:
            from octop.config import load_config
            from octop.infra.connectors.service import ConnectorService

            svc = ConnectorService(
                repo=self.repos.connector_repo,
                secret_repo=self.repos.secret_repo,
                settings_repo=self.repos.settings_repo,
                config=load_config(),
            )
            return set(svc.list_active_mcp_server_names(owner))
        except Exception:
            return set()

    def _schedule_reload_for_device_binding(self, owner: int, device_id: str) -> dict[str, str]:
        """Signal next-turn effectiveness for experts bound to this device."""
        import json as _json

        bound = 0
        try:
            rows = self.repos.agent_repo.list_by_user(owner)
        except Exception:
            rows = []
        for agent in rows:
            try:
                cfg = _json.loads(agent.config_json or "{}")
            except Exception:
                continue
            binding = cfg.get("device_binding") if isinstance(cfg, dict) else None
            if isinstance(binding, dict) and binding.get("device_id") == device_id:
                bound += 1
        _ = bound
        return {"reload_status": "scheduled"}

    async def update(
        self,
        owner: int,
        device_id: str,
        *,
        name: str | None = None,
        permissions: list[str] | None = None,
        roots: list[dict[str, Any]] | None = None,
        remote_grant_mode: str | None = None,
    ) -> dict[str, Any]:
        row = self.owned(owner, device_id)
        if remote_grant_mode is not None and remote_grant_mode not in REMOTE_GRANT_MODES:
            raise device_error("invalid remote_grant_mode")
        if permissions is not None:
            if not set(permissions) <= set(row.capabilities):
                raise OctopError(
                    ErrorCode.DEVICE_INVALID,
                    "UNSUPPORTED_CAPABILITY: permission not in device capabilities",
                )
            if "desktop_control" in permissions and "desktop_view" not in permissions:
                raise device_error("desktop control requires view permission")
        if roots is not None:
            if len(roots) > 20 or len({r["id"] for r in roots}) != len(roots):
                raise device_error("invalid shared roots")
            # DEC-003: never invent paths; only keep roots the device already shared
            # or that match an existing root id/path. New paths require a proposal.
            known = {r["id"]: r for r in row.roots}
            for item in roots:
                prior = known.get(item["id"])
                if prior is None:
                    raise OctopError(
                        ErrorCode.DEVICE_INVALID,
                        "ROOT_NOT_ALLOWED: choose a device-reported root or request via proposal",
                    )
                if item.get("path") != prior.get("path"):
                    raise OctopError(
                        ErrorCode.DEVICE_INVALID,
                        "ROOT_MKDIR_FORBIDDEN: path changes require device consent",
                    )

        desired_permissions = (
            sorted(set(permissions)) if permissions is not None else list(row.permissions)
        )
        desired_roots = roots if roots is not None else list(row.roots)
        added = set(desired_permissions) - set(row.permissions)
        reduced_only = permissions is not None and set(desired_permissions) <= set(row.permissions)
        roots_changed = roots is not None and desired_roots != row.roots
        high_risk_added = bool(added & HIGH_RISK_PERMISSIONS)
        expanding = bool(added) or (
            roots is not None
            and any(
                (not any(r["id"] == d["id"] and r.get("write") for r in row.roots))
                and d.get("write")
                for d in desired_roots
            )
        )

        # Name / mode-only updates, or pure reductions, apply immediately.
        if permissions is None and roots is None:
            updated = self.repos.device_repo.update(
                device_id, name=name, remote_grant_mode=remote_grant_mode
            )
            assert updated is not None
            return self.public(updated)

        mode = remote_grant_mode or row.remote_grant_mode or DEFAULT_REMOTE_GRANT_MODE
        if reduced_only and not roots_changed:
            updated = self.repos.device_repo.update(
                device_id,
                name=name,
                permissions=desired_permissions,
                remote_grant_mode=remote_grant_mode,
            )
            assert updated is not None
            await self._interrupt_device(device_id)
            connection = self._connections.get(device_id)
            if connection is not None:
                with contextlib.suppress(Exception):
                    await connection.send(self.grants(updated))
            return self.public(updated)

        if expanding and not reduced_only:
            client_proto = self._client_protocol.get(device_id, 1)
            if client_proto < GRANT_PROTOCOL_VERSION and device_id in self._connections:
                raise OctopError(
                    ErrorCode.DEVICE_INVALID,
                    "CLIENT_OUTDATED: upgrade the device client to accept expanded grants",
                )
            requires_confirm = high_risk_added or mode == "confirm"
            online = device_id in self._connections
            if not requires_confirm:
                # owner_auto for desktop_*/files_*: apply when online, else fail (AC-005).
                if not online:
                    raise OctopError(
                        ErrorCode.DEVICE_OFFLINE,
                        "device offline; reconnect before applying expanded grants",
                    )
                updated = self.repos.device_repo.update(
                    device_id,
                    name=name,
                    permissions=desired_permissions,
                    roots=desired_roots if roots is not None else None,
                    remote_grant_mode=remote_grant_mode,
                )
                assert updated is not None
                await self._interrupt_device(device_id)
                connection = self._connections.get(device_id)
                if connection is not None:
                    with contextlib.suppress(Exception):
                        await connection.send(self.grants(updated))
                return self.public(updated)

            # High-risk or confirm mode: create a pending proposal.
            return await self.create_grant_proposal(
                owner,
                device_id,
                permissions=desired_permissions,
                roots=desired_roots,
                name=name,
                remote_grant_mode=remote_grant_mode,
            )

        updated = self.repos.device_repo.update(
            device_id,
            name=name,
            permissions=desired_permissions if permissions is not None else None,
            roots=desired_roots if roots is not None else None,
            remote_grant_mode=remote_grant_mode,
        )
        assert updated is not None
        if permissions is not None or roots is not None:
            await self._interrupt_device(device_id)
            connection = self._connections.get(device_id)
            if connection is not None:
                with contextlib.suppress(Exception):
                    await connection.send(self.grants(updated))
        return self.public(updated)

    async def create_grant_proposal(
        self,
        owner: int,
        device_id: str,
        *,
        permissions: list[str],
        roots: list[dict[str, Any]],
        name: str | None = None,
        remote_grant_mode: str | None = None,
    ) -> dict[str, Any]:
        row = self.owned(owner, device_id)
        if not set(permissions) <= set(row.capabilities):
            raise OctopError(
                ErrorCode.DEVICE_INVALID,
                "UNSUPPORTED_CAPABILITY: permission not in device capabilities",
            )
        if len(roots) > 20 or len({r.get("id") for r in roots}) != len(roots):
            raise device_error("invalid shared roots")
        for root in roots:
            if (
                not isinstance(root.get("id"), str)
                or not root["id"]
                or not isinstance(root.get("path"), str)
                or not root["path"]
                or len(root["path"]) > 4096
                or any(ord(c) < 32 for c in root["path"])
            ):
                raise device_error("invalid shared root")
        self._purge_proposals()
        # Replace any prior pending proposal for this device.
        for pid, item in list(self._proposals.items()):
            if item.get("device_id") == device_id and item.get("status") == "pending":
                self._proposals.pop(pid, None)
        proposal_id = new_ulid()
        added = set(permissions) - set(row.permissions)
        known = {r["id"]: r for r in row.roots}
        new_paths = any(
            r["id"] not in known
            or r["path"] != known[r["id"]]["path"]
            or (r.get("write") and not known[r["id"]].get("write"))
            for r in roots
        )
        requires_confirm = (
            bool(added & HIGH_RISK_PERMISSIONS) or row.remote_grant_mode == "confirm" or new_paths
        )
        proposal = {
            "proposal_id": proposal_id,
            "device_id": device_id,
            "owner_user_id": owner,
            "permissions": sorted(set(permissions)),
            "roots": roots,
            "name": name,
            "remote_grant_mode": remote_grant_mode,
            "requires_confirm": requires_confirm,
            "status": "pending",
            "created_at": time.time(),
            "expires_at": time.time() + PENDING_GRANT_TTL_SECONDS,
            "base_grant_version": row.grant_version,
        }
        self._proposals[proposal_id] = proposal
        connection = self._connections.get(device_id)
        if connection is not None:
            client_proto = self._client_protocol.get(device_id, 1)
            if client_proto < GRANT_PROTOCOL_VERSION:
                self._proposals.pop(proposal_id, None)
                raise OctopError(
                    ErrorCode.DEVICE_INVALID,
                    "CLIENT_OUTDATED: upgrade the device client to confirm expanded grants",
                )
            with contextlib.suppress(Exception):
                await connection.send(
                    {
                        "type": "grant_proposal",
                        "proposal_id": proposal_id,
                        "grant_version": row.grant_version,
                        "permissions": proposal["permissions"],
                        "roots": proposal["roots"],
                        "requires_confirm": True,
                        "expires_at": proposal["expires_at"],
                    }
                )
        # Device may have resolved synchronously during send; refresh.
        fresh = self.repos.device_repo.get(device_id)
        assert fresh is not None
        return self.public(fresh)

    async def resolve_grant_proposal(
        self,
        device_id: str,
        proposal_id: str,
        *,
        accept: bool,
        token: str | None = None,
        owner: int | None = None,
    ) -> dict[str, Any]:
        """Resolve from the device wire (token) or owner API."""
        self._purge_proposals()
        proposal = self._proposals.get(proposal_id)
        if proposal is None or proposal.get("device_id") != device_id:
            raise OctopError(ErrorCode.NOT_FOUND, "grant proposal not found")
        if proposal.get("status") != "pending":
            raise device_error("grant proposal already resolved")
        if token is not None:
            self.authenticate(device_id, token)
        elif owner is not None:
            self.owned(owner, device_id)
        elif device_id in self._connections:
            # Authenticated device wire already bound this connection.
            row = self.repos.device_repo.get(device_id)
            if row is None or row.revoked_at is not None:
                raise OctopError(ErrorCode.AUTH_FAILED, "device unavailable")
        else:
            raise OctopError(ErrorCode.AUTH_FAILED, "grant proposal auth required")
        if not accept:
            proposal["status"] = "rejected"
            return {"proposal_id": proposal_id, "status": "rejected"}
        # DEC-005: owner HTTP resolve must not silently land high-risk grants.
        # Only the device (token or bound wire) may accept command_exec/acp_run.
        owner_http = owner is not None and token is None
        if owner_http:
            row = self.repos.device_repo.get(device_id)
            if row is None:
                raise OctopError(ErrorCode.NOT_FOUND, "device not found")
            added = set(proposal["permissions"]) - set(row.permissions)
            known = {r["id"]: r for r in row.roots}
            new_paths = any(
                r["id"] not in known
                or r["path"] != known[r["id"]]["path"]
                or (r.get("write") and not known[r["id"]].get("write"))
                for r in proposal["roots"]
            )
            if added & HIGH_RISK_PERMISSIONS or new_paths:
                raise OctopError(
                    ErrorCode.FORBIDDEN,
                    "DEVICE_CONFIRM_REQUIRED: command_exec/acp_run require "
                    "device-side confirm (DEC-005)",
                )
        updated = self.repos.device_repo.update(
            device_id,
            name=proposal.get("name"),
            permissions=proposal["permissions"],
            roots=proposal["roots"],
            remote_grant_mode=proposal.get("remote_grant_mode"),
        )
        assert updated is not None
        proposal["status"] = "accepted"
        await self._interrupt_device(device_id)
        connection = self._connections.get(device_id)
        if connection is not None:
            with contextlib.suppress(Exception):
                await connection.send(self.grants(updated))
        return self.public(updated)

    def _purge_takeovers(self) -> None:
        now = time.time()
        expired = [
            rid
            for rid, item in self._takeovers.items()
            if item.get("status") == "pending" and float(item.get("expires_at", 0)) < now
        ]
        for rid in expired:
            item = self._takeovers[rid]
            item["status"] = "timeout"
            self._record_takeover_event(item, "timeout")

    def _record_takeover_event(self, item: dict[str, Any], outcome: str) -> None:
        self._takeover_events.append(
            {
                "request_id": item["request_id"],
                "owner_user_id": item["owner_user_id"],
                "from_device_id": item.get("from_device_id"),
                "to_device_id": item["to_device_id"],
                "mode": item["mode"],
                "outcome": outcome,
                "at": time.time(),
            }
        )
        if len(self._takeover_events) > 200:
            self._takeover_events = self._takeover_events[-200:]

    def get_desktop_target(self, owner: int) -> dict[str, Any]:
        """Return current desktop target for owner (0008); does not touch device_binding."""
        self._user(owner)
        self._purge_takeovers()
        device_id = self._desktop_targets.get(owner)
        device = None
        if device_id:
            row = self.repos.device_repo.get_for_owner(device_id, owner)
            if row is None or row.revoked_at is not None:
                self._desktop_targets.pop(owner, None)
                device_id = None
            else:
                device = self.public(row)
        pending = None
        for item in self._takeovers.values():
            if item.get("owner_user_id") == owner and item.get("status") == "pending":
                pending = {
                    "request_id": item["request_id"],
                    "to_device_id": item["to_device_id"],
                    "from_device_id": item.get("from_device_id"),
                    "mode": item["mode"],
                    "status": item["status"],
                    "expires_at": item["expires_at"],
                }
                break
        return {
            "device_id": device_id,
            "device": device,
            "pending_takeover": pending,
            # DEC-002/005: desktop target is independent of expert device_binding
            "note": "desktop_target_independent_of_expert_binding",
        }

    def get_takeover_request(self, owner: int, request_id: str) -> dict[str, Any]:
        self._user(owner)
        self._purge_takeovers()
        item = self._takeovers.get(request_id)
        if item is None or item.get("owner_user_id") != owner:
            raise OctopError(ErrorCode.NOT_FOUND, "desktop takeover request not found")
        return {
            "request_id": item["request_id"],
            "from_device_id": item.get("from_device_id"),
            "to_device_id": item["to_device_id"],
            "mode": item["mode"],
            "status": item["status"],
            "expires_at": item["expires_at"],
            "current_device_id": self._desktop_targets.get(owner),
        }

    def list_takeover_events(self, owner: int, *, limit: int = 50) -> list[dict[str, Any]]:
        self._user(owner)
        limit = max(1, min(int(limit), 100))
        return [e for e in reversed(self._takeover_events) if e.get("owner_user_id") == owner][
            :limit
        ]

    async def request_desktop_switch(
        self,
        owner: int,
        to_device_id: str,
        *,
        mode: str = "view",
    ) -> dict[str, Any]:
        """Start 0008 MVP-S1 desktop target switch; target must Allow takeover."""
        self._user(owner)
        if mode not in DESKTOP_TAKEOVER_MODES:
            raise device_error("invalid desktop takeover mode")
        # AC-010: non-owner forbidden (device exists under another account)
        row = self.repos.device_repo.get(to_device_id)
        if row is None:
            raise OctopError(ErrorCode.NOT_FOUND, "device not found")
        if row.owner_user_id != owner:
            raise OctopError(ErrorCode.FORBIDDEN, "desktop target switch forbidden")
        if row.revoked_at is not None:
            raise OctopError(ErrorCode.FORBIDDEN, "device revoked")
        # AC-003: require desktop_view (and desktop_control when view_control)
        needed = {"desktop_view"}
        if mode == "view_control":
            needed.add("desktop_control")
        missing = needed - set(row.permissions)
        if missing or not needed <= set(row.capabilities):
            raise OctopError(
                ErrorCode.FORBIDDEN,
                "DESKTOP_PERMISSION_REQUIRED: grant desktop_view"
                + (" and desktop_control" if mode == "view_control" else "")
                + " via 0005 before takeover",
            )
        if to_device_id not in self._connections:
            raise OctopError(ErrorCode.DEVICE_OFFLINE, "device offline")

        current = self._desktop_targets.get(owner)
        if self.owner_trusted(row):
            self._desktop_targets[owner] = to_device_id
            result = {
                "request_id": None,
                "status": "accepted",
                "from_device_id": current,
                "to_device_id": to_device_id,
                "mode": mode,
                "current_device_id": to_device_id,
                "owner_user_id": owner,
            }
            self._record_takeover_event(result, "accepted")
            return result
        if current == to_device_id:
            return {
                "request_id": None,
                "status": "accepted",
                "from_device_id": current,
                "to_device_id": to_device_id,
                "mode": mode,
                "current_device_id": current,
            }

        self._purge_takeovers()
        # Replace any prior pending takeover for this owner.
        for rid, item in list(self._takeovers.items()):
            if item.get("owner_user_id") == owner and item.get("status") == "pending":
                item["status"] = "cancelled"
                self._takeovers.pop(rid, None)

        request_id = new_ulid()
        owner_user = self.repos.user_repo.get(owner)
        owner_label = getattr(owner_user, "username", None) or str(owner)
        payload = {
            "request_id": request_id,
            "owner_user_id": owner,
            "owner_label": owner_label,
            "from_device_id": current,
            "to_device_id": to_device_id,
            "mode": mode,
            "status": "pending",
            "created_at": time.time(),
            "expires_at": time.time() + PENDING_TAKEOVER_TTL_SECONDS,
        }
        self._takeovers[request_id] = payload
        connection = self._connections[to_device_id]
        with contextlib.suppress(Exception):
            await connection.send(
                {
                    "type": "desktop_takeover",
                    "request_id": request_id,
                    "owner_label": owner_label,
                    "mode": mode,
                    "from_device_id": current,
                    "expires_at": payload["expires_at"],
                }
            )
        # Device may have resolved synchronously during send.
        fresh = self._takeovers.get(request_id, payload)
        return {
            "request_id": request_id,
            "status": fresh["status"],
            "from_device_id": current,
            "to_device_id": to_device_id,
            "mode": mode,
            "expires_at": fresh["expires_at"],
            "current_device_id": self._desktop_targets.get(owner),
        }

    async def resolve_desktop_takeover(
        self,
        device_id: str,
        request_id: str,
        *,
        accept: bool,
    ) -> dict[str, Any]:
        """Resolve takeover from the controlled device wire (DEC-001)."""
        self._purge_takeovers()
        item = self._takeovers.get(request_id)
        if item is None or item.get("to_device_id") != device_id:
            raise OctopError(ErrorCode.NOT_FOUND, "desktop takeover request not found")
        if item.get("status") != "pending":
            raise device_error("desktop takeover already resolved")
        if not accept:
            item["status"] = "rejected"
            self._record_takeover_event(item, "rejected")
            return {
                "request_id": request_id,
                "status": "rejected",
                "current_device_id": self._desktop_targets.get(item["owner_user_id"]),
            }
        # Cold standby (DEC-003): bind new target; no hot session migration.
        owner = int(item["owner_user_id"])
        self._desktop_targets[owner] = device_id
        item["status"] = "accepted"
        self._record_takeover_event(item, "accepted")
        return {
            "request_id": request_id,
            "status": "accepted",
            "current_device_id": device_id,
            "from_device_id": item.get("from_device_id"),
            "to_device_id": device_id,
            "mode": item["mode"],
        }

    async def revoke(self, owner: int, device_id: str) -> dict[str, Any]:
        self.owned(owner, device_id, active=False)
        row = self.repos.device_repo.revoke(device_id)
        assert row is not None
        await self._interrupt_device(device_id)
        connection = self._connections.get(device_id)
        if connection is not None:
            if self._client_protocol.get(device_id, 1) >= CLIENT_PROTOCOL_VERSION:
                with contextlib.suppress(Exception):
                    await connection.send({"type": "revoked"})
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
        if device_id not in self._connections:
            raise OctopError(ErrorCode.DEVICE_OFFLINE, "device offline")
        if action not in {"ping", "status"} and row.policy_revision != row.applied_policy_revision:
            raise device_error("POLICY_PENDING: device has not applied its policy", status=409)
        if action.startswith("fs.") and not self.owner_trusted(row):
            raise OctopError(
                ErrorCode.FORBIDDEN, "native filesystem requires trusted device protocol v3"
            )
        if action.startswith(("fs.upload.", "fs.download.")) and (
            (row.runtime_metadata or {}).get("transfer_protocol_version") != 1
        ):
            raise device_error(
                "CLIENT_OUTDATED: device does not support native file transfers", status=409
            )
        if action.startswith("jobs.") and (
            not self.owner_trusted(row)
            or (row.runtime_metadata or {}).get("job_protocol_version") != 1
        ):
            raise device_error(
                "CLIENT_OUTDATED: device does not support persistent Jobs", status=409
            )
        if required and (required not in row.permissions or required not in row.capabilities):
            raise OctopError(ErrorCode.FORBIDDEN, "device capability not granted")
        if action.startswith("capabilities.") and (
            not self.owner_trusted(row)
            or (row.runtime_metadata or {}).get("capability_protocol_version") != 1
        ):
            raise device_error(
                "CLIENT_OUTDATED: device does not support capability discovery", status=409
            )
        if action.startswith("git.") and (
            not self.owner_trusted(row)
            or (row.runtime_metadata or {}).get("workbench_protocol_version") != 1
        ):
            raise device_error("CLIENT_OUTDATED: device does not support native Git", status=409)
        if action.startswith("terminal.") and (
            not self.owner_trusted(row)
            or (row.runtime_metadata or {}).get("terminal_protocol_version") != 1
        ):
            raise device_error(
                "CLIENT_OUTDATED: device does not support native terminal", status=409
            )
        if action.startswith("browser.") and (
            not self.owner_trusted(row)
            or (row.runtime_metadata or {}).get("browser_protocol_version") != 1
        ):
            raise device_error(
                "CLIENT_OUTDATED: device does not support device browser", status=409
            )
        if agent_id:
            agent = self.repos.agent_repo.get(agent_id)
            if agent is None or agent.user_id != owner:
                raise OctopError(ErrorCode.FORBIDDEN, "agent cannot use this device")
        if not self.owner_trusted(row) and (
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
        record_operation: bool = False,
        execution_context_id: str | None = None,
    ) -> dict[str, Any]:
        if action.startswith("browser."):
            from octop.infra.execution.service import ExecutionService

            if execution_context_id is None:
                raise OctopError(ErrorCode.FORBIDDEN, "browser calls require an execution context")
            context, params = ExecutionService(self)._prepare(
                owner, execution_context_id, action, params, actor_agent_id=agent_id
            )
            if context.target_kind != "device" or context.device_id != device_id:
                raise OctopError(ErrorCode.FORBIDDEN, "browser context targets another device")
            agent_id = context.agent_id
            expected_version = context.grant_version
        if (
            action == "command.run"
            and not allow_command
            and not self.owner_trusted(self.owned(owner, device_id))
        ):
            raise OctopError(ErrorCode.FORBIDDEN, "command requires human confirmation")
        if action.startswith("acp.") and not allow_acp:
            raise OctopError(ErrorCode.FORBIDDEN, "ACP calls require an expert device binding")
        row = self.authorize(owner, device_id, action, params, agent_id=agent_id)
        if len(self._pending) >= 128:
            raise device_error("device operation capacity reached", status=429)
        if expected_version is not None and row.grant_version != expected_version:
            raise OctopError(ErrorCode.FORBIDDEN, "device permission changed")
        connection = self._connections[device_id]
        audit = (record_operation or request_id is None) and action in {
            "command.run",
            "jobs.start",
            "jobs.cancel",
            "git.restore",
            "fs.write",
            "fs.edit",
            "fs.mkdir",
            "fs.move",
            "fs.remove",
            "fs.upload.begin",
            "fs.upload.commit",
            "fs.upload.abort",
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
                {
                    "root_id": params.get("root_id"),
                    "runner": params.get("runner"),
                    "execution_context_id": params.get("execution_context_id"),
                }
                if action == "acp.open"
                else {}
                if action == "acp.close"
                else {
                    "kind": params.get("kind"),
                    "execution_context_id": params.get("execution_context_id"),
                }
                if action == "desktop.input"
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
            if action in {"fs.upload.begin", "fs.download.begin", "fs.upload.commit"}:
                wait_timeout = 1800  # Streaming checksum preparation; heartbeats stay independent.
            result = await asyncio.wait_for(future, wait_timeout)
            if audit:
                self.repos.device_repo.update_operation(
                    request_id,
                    status=result_status(action, result),
                    result=ledger_result(action, result),
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
        if action.startswith("browser."):
            raise OctopError(
                ErrorCode.FORBIDDEN, "browser streams require the immediate execution context API"
            )
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
            status="pending_confirmation"
            if action == "command.run" and not self.owner_trusted(row)
            else "queued",
        )
        if op.status == "queued":
            self._launch(op)
        return op.public()

    def _record_execution_receipt(self, operation_id: str, owner: int) -> None:
        from octop.infra.db.repos.execution import ExecutionContextRepo
        from octop.infra.execution.events import (
            STREAM_ACTIONS,
            RunInspectionService,
            bound_receipt_fields,
            command_preview_from_params,
        )

        op = self.repos.device_repo.get_operation(operation_id, owner)
        if op is None or op.action in STREAM_ACTIONS:
            return
        inspect = RunInspectionService(self.repos)
        event_id = f"operation:{operation_id}"
        existing = inspect.events.get(owner, event_id)
        if existing is not None:
            # Always advance a receipt that was opened at submit time. Peer
            # ask_agent can leave context.agent_id on the host while op.agent_id
            # is the member; device_receipt's thread ownership check would
            # otherwise skip the terminal status and block work_step evidence.
            summary = {
                **(existing.get("payload") or {}),
                "operation_id": operation_id,
                "action": op.action,
                "device_id": op.device_id,
            }
            preview = command_preview_from_params(op.params or {})
            if preview and not summary.get("command_preview"):
                summary["command_preview"] = preview
            if op.result is not None:
                summary["receipt"] = bound_receipt_fields(op.result)
            inspect.events.save(
                event_id=event_id,
                owner=owner,
                agent_id=existing.get("agent_id"),
                thread_id=existing.get("thread_id"),
                run_id=str(existing["run_id"]),
                context_id=existing.get("context_id"),
                kind="device",
                status=op.status,
                payload=summary,
            )
            return
        context_id = op.params.get("execution_context_id")
        context = (
            ExecutionContextRepo(self.repos.db).get(owner, context_id)
            if isinstance(context_id, str)
            else None
        )
        if context and context.device_id == op.device_id and context.agent_id == op.agent_id:
            inspect.device_receipt(
                context, operation_id, op.action, op.status, op.params, op.result
            )

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
        self._record_execution_receipt(op.operation_id, op.owner_user_id)
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

        finally:
            self._record_execution_receipt(op.operation_id, op.owner_user_id)

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
        if self.local_execution is not None:
            await self.local_execution.close()
        for task in list(self._jobs.values()):
            task.cancel()
        await asyncio.gather(*list(self._jobs.values()), return_exceptions=True)
        for connection in list(self._connections.values()):
            self.disconnect(connection)
            with contextlib.suppress(Exception):
                await connection.close()
        self._pairings.clear()
