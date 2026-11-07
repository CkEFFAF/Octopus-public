"""Device-side helpers for 0044 transfer.negotiate / receipt (control plane).

Does not implement the TLS data plane. Validates ticket bindings and builds
receipt frames. Enrollment tokens must never be used as tickets.
"""

from __future__ import annotations

from typing import Any

from octop.infra.devices.transfer_session import (
    binding_matches,
    parse_ticket,
    verify_ticket,
)


def handle_negotiate(
    frame: dict[str, Any],
    *,
    local_device_id: str,
    ticket_secret: bytes | None = None,
) -> dict[str, Any]:
    """Validate a Hub negotiate frame against local identity; return ack summary.

    When ``ticket_secret`` is provided, full HMAC verification runs. Otherwise only
    structural binding checks against the ticket payload are applied (executor may
    not hold the Hub signing key — Hub remains authoritative).
    """
    if frame.get("type") != "transfer.negotiate":
        raise ValueError("not a negotiate frame")
    ticket = str(frame.get("ticket") or "")
    role = str(frame.get("role") or "")
    peer = str(frame.get("peer_device_id") or "")
    if ticket_secret is not None:
        claims = verify_ticket(ticket_secret, ticket)
    else:
        claims = parse_ticket(ticket)
    path_scope = frame.get("path_scope") if isinstance(frame.get("path_scope"), dict) else None
    size = frame.get("size")
    sha256 = frame.get("sha256")
    if not binding_matches(
        claims,
        local_device_id=local_device_id,
        role=role,
        peer_device_id=peer,
        size=int(size) if size is not None else None,
        sha256=str(sha256) if sha256 is not None else None,
        path_scope={k: str(v) for k, v in (path_scope or {}).items()},
    ):
        raise ValueError("TRANSFER_PEER_MISMATCH")
    return {
        "transfer_id": claims.transfer_id,
        "role": role,
        "peer_device_id": peer,
        "size": claims.size,
        "sha256": claims.sha256,
        "accepted": True,
    }


def receipt_frame(
    *,
    transfer_id: str,
    device_id: str,
    phase: str,
    bytes_done: int | None = None,
    sha256: str | None = None,
    transport_used: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {
        "type": "transfer.receipt",
        "transfer_id": transfer_id,
        "device_id": device_id,
        "phase": phase,
        "schema_version": 1,
    }
    if bytes_done is not None:
        out["bytes_done"] = int(bytes_done)
    if sha256 is not None:
        out["sha256"] = str(sha256).lower()
    if transport_used is not None:
        out["transport_used"] = transport_used
    return out


__all__ = ["handle_negotiate", "receipt_frame"]
