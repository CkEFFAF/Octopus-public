"""Lifecycle for restricted agent access tokens (prefix oaa_)."""

from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

from octop.infra.auth.ldap.throttle import LdapBindThrottle
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.ulid import new_ulid

AGENT_KEY_PREFIX = "oaa_"
BROWSER_KEY_PREFIX = "oak_"

AGENT_SCOPES = frozenset(
    {
        "experts.read",
        "tasks.create",
        "tasks.read",
        "tasks.input",
        "tasks.cancel",
        "resources.read",
    }
)

_MAX_ACTIVE = 20


@dataclass(frozen=True)
class MachinePrincipal:
    """Authenticated machine credential (never a full browser session)."""

    credential_id: str
    owner_user_id: int
    scopes: frozenset[str]
    expert_allowlist: frozenset[str]
    allow_existing_threads: bool
    actor_kind: str = "machine"

    def has_scope(self, scope: str) -> bool:
        return scope in self.scopes

    def allows_expert(self, expert_id: str) -> bool:
        return expert_id in self.expert_allowlist


class AgentAccessKeyService:
    def __init__(self, repos: RepoBundle) -> None:
        self.repos = repos
        self.throttle = LdapBindThrottle(max_attempts=5, window_seconds=300, block_seconds=300)

    @staticmethod
    def public(row: dict[str, Any]) -> dict[str, Any]:
        scopes = json.loads(row["scopes_json"])
        experts = json.loads(row["expert_ids_json"])
        return {
            "key_id": row["key_id"],
            "owner_user_id": int(row["owner_user_id"]),
            "name": row["name"],
            "prefix": AGENT_KEY_PREFIX,
            "scopes": scopes,
            "expert_ids": experts,
            "allow_existing_threads": bool(row.get("allow_existing_threads")),
            "expires_at": float(row["expires_at"]),
            "revoked_at": row.get("revoked_at"),
            "last_used_at": row.get("last_used_at"),
            "created_at": float(row["created_at"]),
        }

    def _user(self, owner: int) -> None:
        user = self.repos.user_repo.get(owner)
        if user is None or user.disabled:
            raise OctopError(ErrorCode.AUTH_FAILED, "invalid agent access key")

    def _active(self, row: dict[str, Any]) -> None:
        if row["revoked_at"] is not None or float(row["expires_at"]) <= time.time():
            raise OctopError(ErrorCode.AUTH_FAILED, "invalid agent access key")
        self._user(int(row["owner_user_id"]))

    @staticmethod
    def _parse_scopes(scopes: list[str]) -> list[str]:
        cleaned = [str(s).strip() for s in scopes if str(s).strip()]
        if not cleaned:
            raise OctopError(ErrorCode.DEVICE_INVALID, "scopes required", status=422)
        unknown = [s for s in cleaned if s not in AGENT_SCOPES]
        if unknown:
            raise OctopError(
                ErrorCode.DEVICE_INVALID, f"unknown scopes: {', '.join(unknown)}", status=422
            )
        return sorted(set(cleaned))

    @staticmethod
    def _parse_experts(expert_ids: list[str]) -> list[str]:
        cleaned = [str(e).strip() for e in expert_ids if str(e).strip()]
        if not cleaned:
            raise OctopError(ErrorCode.DEVICE_INVALID, "expert_ids required", status=422)
        return sorted(set(cleaned))

    def create(
        self,
        owner: int,
        *,
        name: str,
        days: int,
        scopes: list[str],
        expert_ids: list[str],
        allow_existing_threads: bool = False,
    ) -> dict[str, Any]:
        self._user(owner)
        if not name.strip() or len(name) > 120 or not 1 <= days <= 365:
            raise OctopError(ErrorCode.DEVICE_INVALID, "invalid agent access key options")
        scope_list = self._parse_scopes(scopes)
        expert_list = self._parse_experts(expert_ids)
        rows = self.repos.agent_access_key_repo.list_for_owner(owner)
        active = sum(
            1
            for row in rows
            if row["revoked_at"] is None and float(row["expires_at"]) > time.time()
        )
        if active >= _MAX_ACTIVE:
            raise OctopError(ErrorCode.DEVICE_INVALID, "agent access key limit reached", status=429)
        secret = AGENT_KEY_PREFIX + secrets.token_urlsafe(32)
        row: dict[str, Any] = {
            "key_id": new_ulid(),
            "owner_user_id": owner,
            "name": name.strip(),
            "secret_hash": hashlib.sha256(secret.encode()).hexdigest(),
            "scopes_json": json.dumps(scope_list),
            "expert_ids_json": json.dumps(expert_list),
            "allow_existing_threads": int(bool(allow_existing_threads)),
            "expires_at": time.time() + days * 86400,
            "created_at": time.time(),
        }
        self.repos.agent_access_key_repo.create(row)
        self.repos.audit_repo.write(
            actor=str(owner), action="auth.agent_access_key_created", target=row["key_id"]
        )
        stored = self.repos.agent_access_key_repo.get(row["key_id"]) or row
        return {"key": self.public(stored), "secret": secret}

    def list_keys(self, owner: int) -> list[dict[str, Any]]:
        self._user(owner)
        return [self.public(row) for row in self.repos.agent_access_key_repo.list_for_owner(owner)]

    def revoke(self, owner: int, key_id: str) -> None:
        self._user(owner)
        if not self.repos.agent_access_key_repo.revoke(owner, key_id):
            raise OctopError(ErrorCode.NOT_FOUND, "agent access key not found")
        self.repos.audit_repo.write(
            actor=str(owner), action="auth.agent_access_key_revoked", target=key_id
        )

    def authenticate(self, secret: str, client_ip: str) -> MachinePrincipal:
        retry = self.throttle.retry_after("agent-access-key", client_ip)
        if retry:
            raise OctopError(
                ErrorCode.LOGIN_LOCKED,
                "agent access key login throttled",
                details={"minutes": 5, "retry_after_seconds": retry},
            )
        if not secret.startswith(AGENT_KEY_PREFIX):
            self.throttle.record_failure("agent-access-key", client_ip)
            raise OctopError(ErrorCode.AUTH_FAILED, "invalid agent access key")
        if secret.startswith(BROWSER_KEY_PREFIX):
            self.throttle.record_failure("agent-access-key", client_ip)
            raise OctopError(ErrorCode.AUTH_FAILED, "browser access key not allowed here")
        row = self.repos.agent_access_key_repo.find_hash(
            hashlib.sha256(secret.encode()).hexdigest()
        )
        try:
            if row is None:
                raise OctopError(ErrorCode.AUTH_FAILED, "invalid agent access key")
            self._active(row)
        except OctopError:
            self.throttle.record_failure("agent-access-key", client_ip)
            raise
        self.throttle.clear("agent-access-key", client_ip)
        self.repos.agent_access_key_repo.touch(row["key_id"])
        return self.principal_from_row(row)

    def validate_credential(self, key_id: str, owner: int) -> MachinePrincipal:
        row = self.repos.agent_access_key_repo.get(key_id)
        if row is None or int(row["owner_user_id"]) != int(owner):
            raise OctopError(ErrorCode.AUTH_FAILED, "invalid agent access key session")
        self._active(row)
        return self.principal_from_row(row)

    def principal_from_row(self, row: dict[str, Any]) -> MachinePrincipal:
        scopes = frozenset(json.loads(row["scopes_json"]))
        experts = frozenset(json.loads(row["expert_ids_json"]))
        return MachinePrincipal(
            credential_id=row["key_id"],
            owner_user_id=int(row["owner_user_id"]),
            scopes=scopes,
            expert_allowlist=experts,
            allow_existing_threads=bool(row.get("allow_existing_threads")),
        )

    def grant_object(self, principal: MachinePrincipal, object_kind: str, object_id: str) -> None:
        self.repos.agent_access_key_repo.grant_object(
            principal.credential_id, object_kind, object_id
        )

    def owns_object(self, principal: MachinePrincipal, object_kind: str, object_id: str) -> bool:
        return self.repos.agent_access_key_repo.has_object_grant(
            principal.credential_id, object_kind, object_id
        )
