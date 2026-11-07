"""0044 transfer session domain: status machine, tickets, capability checks.

Tickets are short-lived HMAC-signed bearer proofs bound to transfer_id, devices,
size/sha256, path scope, grant versions, and expiry. Enrollment tokens are never
used as tickets. Plaintext tickets must not be logged.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any

TRANSFER_STATUSES = frozenset(
    {
        "queued",
        "negotiating",
        "transferring",
        "verifying",
        "pending_receipt",
        "completed",
        "failed",
        "cancelled",
        "unknown",
    }
)
TERMINAL_STATUSES = frozenset({"completed", "failed", "cancelled", "unknown"})
PREFERRED_TRANSPORTS = frozenset({"auto", "direct", "hub"})
ACTUAL_TRANSPORTS = frozenset({"direct", "hub"})
TICKET_TTL_SECONDS = 600
TRANSFER_SCHEMA_VERSION = 1
MIN_P2P_PROTOCOL = 2


@dataclass(frozen=True)
class TicketClaims:
    transfer_id: str
    source_device_id: str
    target_device_id: str
    source_root_id: str
    source_path: str
    target_root_id: str
    target_path: str
    size: int
    sha256: str
    source_grant_version: int
    target_grant_version: int
    policy_version: int
    expires_at: float
    nonce: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "transfer_id": self.transfer_id,
            "source_device_id": self.source_device_id,
            "target_device_id": self.target_device_id,
            "source_root_id": self.source_root_id,
            "source_path": self.source_path,
            "target_root_id": self.target_root_id,
            "target_path": self.target_path,
            "size": self.size,
            "sha256": self.sha256,
            "source_grant_version": self.source_grant_version,
            "target_grant_version": self.target_grant_version,
            "policy_version": self.policy_version,
            "expires_at": self.expires_at,
            "nonce": self.nonce,
        }

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> TicketClaims:
        return cls(
            transfer_id=str(raw["transfer_id"]),
            source_device_id=str(raw["source_device_id"]),
            target_device_id=str(raw["target_device_id"]),
            source_root_id=str(raw["source_root_id"]),
            source_path=str(raw["source_path"]),
            target_root_id=str(raw["target_root_id"]),
            target_path=str(raw["target_path"]),
            size=int(raw["size"]),
            sha256=str(raw["sha256"]).lower(),
            source_grant_version=int(raw["source_grant_version"]),
            target_grant_version=int(raw["target_grant_version"]),
            policy_version=int(raw["policy_version"]),
            expires_at=float(raw["expires_at"]),
            nonce=str(raw["nonce"]),
        )


def ticket_hash(ticket: str) -> str:
    return hashlib.sha256(ticket.encode("utf-8")).hexdigest()


def mint_ticket(secret: bytes, claims: TicketClaims) -> str:
    payload = json.dumps(claims.to_dict(), separators=(",", ":"), sort_keys=True).encode("utf-8")
    sig = hmac.new(secret, payload, hashlib.sha256).digest()
    return (
        base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")
        + "."
        + base64.urlsafe_b64encode(sig).decode("ascii").rstrip("=")
    )


def _b64decode(part: str) -> bytes:
    pad = "=" * (-len(part) % 4)
    return base64.urlsafe_b64decode(part + pad)


def parse_ticket(ticket: str) -> TicketClaims:
    try:
        body, _, _sig = ticket.partition(".")
        if not body or not _sig:
            raise ValueError("malformed")
        raw = json.loads(_b64decode(body))
        if not isinstance(raw, dict):
            raise ValueError("malformed")
        return TicketClaims.from_dict(raw)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("TRANSFER_TICKET_INVALID") from exc


def verify_ticket(
    secret: bytes,
    ticket: str,
    *,
    now: float | None = None,
    expect: TicketClaims | None = None,
    consumed: bool = False,
    revoked: bool = False,
) -> TicketClaims:
    if revoked or consumed:
        raise ValueError("TRANSFER_TICKET_INVALID")
    try:
        body, _, sig = ticket.partition(".")
        if not body or not sig:
            raise ValueError("malformed")
        payload = _b64decode(body)
        expected_sig = hmac.new(secret, payload, hashlib.sha256).digest()
        if not hmac.compare_digest(expected_sig, _b64decode(sig)):
            raise ValueError("bad sig")
        claims = TicketClaims.from_dict(json.loads(payload))
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise ValueError("TRANSFER_TICKET_INVALID") from exc
    ts = time.time() if now is None else now
    if claims.expires_at < ts:
        raise ValueError("TRANSFER_TICKET_INVALID")
    if expect is not None and claims != expect:
        raise ValueError("TRANSFER_PEER_MISMATCH")
    return claims


def device_supports_p2p(
    *,
    runtime_metadata: dict[str, Any] | None,
    capabilities: list[str] | None = None,
) -> bool:
    meta = runtime_metadata or {}
    try:
        version = int(meta.get("transfer_protocol_version") or 0)
    except (TypeError, ValueError):
        version = 0
    if version >= MIN_P2P_PROTOCOL:
        return True
    caps = capabilities or []
    return "p2p_file_transfer" in caps


def normalize_preferred(value: str | None) -> str:
    preferred = (value or "auto").strip().lower()
    if preferred not in PREFERRED_TRANSPORTS:
        return "auto"
    return preferred


def can_transition(current: str, nxt: str) -> bool:
    if current == nxt:
        return True
    if current in TERMINAL_STATUSES:
        return False
    order = {
        "queued": 0,
        "negotiating": 1,
        "transferring": 2,
        "verifying": 3,
        "pending_receipt": 4,
        "completed": 5,
        "failed": 5,
        "cancelled": 5,
        "unknown": 5,
    }
    if nxt in {"failed", "cancelled", "unknown"}:
        return current not in TERMINAL_STATUSES
    if nxt == "completed":
        return current in {"verifying", "pending_receipt", "transferring"}
    return order.get(nxt, -1) >= order.get(current, -1)


def new_ticket_claims(
    *,
    transfer_id: str,
    source_device_id: str,
    target_device_id: str,
    source_root_id: str,
    source_path: str,
    target_root_id: str,
    target_path: str,
    size: int,
    sha256: str,
    source_grant_version: int,
    target_grant_version: int,
    policy_version: int = 1,
    ttl_seconds: int = TICKET_TTL_SECONDS,
    now: float | None = None,
) -> TicketClaims:
    ts = time.time() if now is None else now
    return TicketClaims(
        transfer_id=transfer_id,
        source_device_id=source_device_id,
        target_device_id=target_device_id,
        source_root_id=source_root_id,
        source_path=source_path,
        target_root_id=target_root_id,
        target_path=target_path,
        size=int(size),
        sha256=str(sha256).lower(),
        source_grant_version=int(source_grant_version),
        target_grant_version=int(target_grant_version),
        policy_version=int(policy_version),
        expires_at=ts + ttl_seconds,
        nonce=secrets.token_urlsafe(16),
    )


def binding_matches(
    claims: TicketClaims,
    *,
    local_device_id: str,
    role: str,
    peer_device_id: str,
    size: int | None = None,
    sha256: str | None = None,
    path_scope: dict[str, str] | None = None,
) -> bool:
    if role == "source":
        if local_device_id != claims.source_device_id:
            return False
        if peer_device_id != claims.target_device_id:
            return False
    elif role == "target":
        if local_device_id != claims.target_device_id:
            return False
        if peer_device_id != claims.source_device_id:
            return False
    else:
        return False
    if size is not None and int(size) != claims.size:
        return False
    if sha256 is not None and str(sha256).lower() != claims.sha256:
        return False
    if path_scope:
        root_id = str(path_scope.get("root_id", ""))
        path = str(path_scope.get("path", ""))
        if role == "source":
            if root_id != claims.source_root_id or path != claims.source_path:
                return False
        else:
            if root_id != claims.target_root_id or path != claims.target_path:
                return False
    return True


__all__ = [
    "ACTUAL_TRANSPORTS",
    "MIN_P2P_PROTOCOL",
    "PREFERRED_TRANSPORTS",
    "TERMINAL_STATUSES",
    "TICKET_TTL_SECONDS",
    "TRANSFER_SCHEMA_VERSION",
    "TRANSFER_STATUSES",
    "TicketClaims",
    "binding_matches",
    "can_transition",
    "device_supports_p2p",
    "mint_ticket",
    "new_ticket_claims",
    "normalize_preferred",
    "parse_ticket",
    "ticket_hash",
    "verify_ticket",
]
