"""Revocable high-entropy credentials for browsers and native device enrollment."""

from __future__ import annotations

import hashlib
import secrets
import time
from typing import Any

from octop.infra.auth.ldap.throttle import LdapBindThrottle
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.utils.ulid import new_ulid


class AccessKeyService:
    def __init__(self, repos: RepoBundle) -> None:
        self.repos = repos
        self.throttle = LdapBindThrottle(max_attempts=5, window_seconds=300, block_seconds=300)

    @staticmethod
    def public(row: dict[str, Any]) -> dict[str, Any]:
        return {key: value for key, value in row.items() if key != "secret_hash"}

    def create(
        self, owner: int, name: str, days: int, allow_browser: bool, allow_devices: bool
    ) -> dict[str, Any]:
        self._user(owner)
        if (
            not name.strip()
            or len(name) > 120
            or not 1 <= days <= 365
            or not (allow_browser or allow_devices)
        ):
            raise OctopError(ErrorCode.DEVICE_INVALID, "invalid access key options")
        rows = self.repos.access_key_repo.list_for_owner(owner)
        if sum(row["revoked_at"] is None and row["expires_at"] > time.time() for row in rows) >= 20:
            raise OctopError(ErrorCode.DEVICE_INVALID, "access key limit reached", status=429)
        secret = "oak_" + secrets.token_urlsafe(32)
        row: dict[str, Any] = {
            "key_id": new_ulid(),
            "owner_user_id": owner,
            "name": name.strip(),
            "secret_hash": hashlib.sha256(secret.encode()).hexdigest(),
            "allow_browser": int(allow_browser),
            "allow_devices": int(allow_devices),
            "expires_at": time.time() + days * 86400,
            "created_at": time.time(),
        }
        self.repos.access_key_repo.create(row)
        self.repos.audit_repo.write(
            actor=str(owner), action="auth.access_key_created", target=row["key_id"]
        )
        return {
            "key": self.public(self.repos.access_key_repo.get(row["key_id"]) or row),
            "secret": secret,
        }

    def _user(self, owner: int) -> None:
        user = self.repos.user_repo.get(owner)
        if user is None or user.disabled:
            raise OctopError(ErrorCode.AUTH_FAILED, "invalid access key")

    def validate_session(self, owner: int, key_id: str) -> None:
        row = self.repos.access_key_repo.get(key_id)
        if row is None or row["owner_user_id"] != owner or not row["allow_browser"]:
            raise OctopError(ErrorCode.AUTH_FAILED, "invalid access key session")
        self._active(row)

    def _active(self, row: dict[str, Any]) -> None:
        if row["revoked_at"] is not None or row["expires_at"] <= time.time():
            raise OctopError(ErrorCode.AUTH_FAILED, "invalid access key")
        self._user(int(row["owner_user_id"]))

    def authenticate(self, secret: str, scope: str, client_ip: str) -> dict[str, Any]:
        retry = self.throttle.retry_after("access-key", client_ip)
        if retry:
            raise OctopError(
                ErrorCode.LOGIN_LOCKED,
                "access key login throttled",
                details={"minutes": 5, "retry_after_seconds": retry},
            )
        row = (
            self.repos.access_key_repo.find_hash(hashlib.sha256(secret.encode()).hexdigest())
            if secret.startswith("oak_")
            else None
        )
        try:
            if row is None or not row.get(f"allow_{scope}"):
                raise OctopError(ErrorCode.AUTH_FAILED, "invalid access key")
            self._active(row)
        except OctopError:
            self.throttle.record_failure("access-key", client_ip)
            raise
        self.throttle.clear("access-key", client_ip)
        self.repos.access_key_repo.touch(row["key_id"])
        self.repos.audit_repo.write(
            actor=str(row["owner_user_id"]), action=f"auth.access_key_{scope}", target=row["key_id"]
        )
        return row

    def list_keys(self, owner: int) -> list[dict[str, Any]]:
        self._user(owner)
        return [self.public(row) for row in self.repos.access_key_repo.list_for_owner(owner)]

    def revoke(self, owner: int, key_id: str) -> None:
        self._user(owner)
        if not self.repos.access_key_repo.revoke(owner, key_id):
            raise OctopError(ErrorCode.NOT_FOUND, "access key not found")
        self.repos.audit_repo.write(
            actor=str(owner), action="auth.access_key_revoked", target=key_id
        )
