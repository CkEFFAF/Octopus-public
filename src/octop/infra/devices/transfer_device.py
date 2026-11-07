"""Device-side helpers for 0044 transfer.negotiate / TLS data plane / receipts.

Validates ticket bindings, runs the peer TLS data plane, and builds receipt /
offer frames. Enrollment tokens must never be used as tickets.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from pathlib import Path
from typing import Any

from octop.infra.devices.transfer_protocol import offer_frame, peer_frame
from octop.infra.devices.transfer_session import (
    TicketClaims,
    binding_matches,
    parse_ticket,
    verify_ticket,
)
from octop.infra.devices.transfer_tls import PeerTlsListener, send_file_over_tls


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
        "ticket": ticket,
        "claims": claims,
        "path_scope": {k: str(v) for k, v in (path_scope or {}).items()},
        "preferred_transport": str(frame.get("preferred_transport") or "auto"),
        "accepted": True,
    }


def resolve_root_path(
    roots: dict[str, dict[str, Any]] | list[dict[str, Any]],
    root_id: str,
    rel_path: str,
) -> Path:
    """Map ticket path_scope onto a local executor root."""
    mapping: dict[str, dict[str, Any]]
    if isinstance(roots, dict):
        mapping = roots
    else:
        mapping = {str(r["id"]): r for r in roots if isinstance(r, dict) and "id" in r}
    root = mapping.get(root_id)
    if root is None or not root.get("path"):
        raise ValueError("TRANSFER_PATH_DENIED")
    base = Path(str(root["path"])).resolve()
    target = (base / rel_path).resolve()
    if base != target and base not in target.parents:
        raise ValueError("TRANSFER_PATH_DENIED")
    return target


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


async def run_direct_target(
    *,
    ticket: str,
    claims: TicketClaims,
    dest_path: Path,
    device_id: str,
    send_to_hub: Callable[[dict[str, Any]], Any],
    overwrite: bool = False,
    host: str = "127.0.0.1",
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Listen on TLS, publish offer to Hub, receive file, emit completed receipt."""
    listener = PeerTlsListener(
        ticket=ticket,
        claims=claims,
        dest_path=dest_path,
        overwrite=overwrite,
        host=host,
        timeout=timeout,
    )
    listen_host, port = await asyncio.to_thread(listener.start)
    await send_to_hub(
        offer_frame(
            transfer_id=claims.transfer_id,
            device_id=device_id,
            host=listen_host,
            port=port,
        )
    )
    try:
        result = await asyncio.to_thread(listener.wait, timeout + 5)
    except BaseException:
        listener.close()
        await send_to_hub(
            receipt_frame(
                transfer_id=claims.transfer_id,
                device_id=device_id,
                phase="failed",
                transport_used="direct",
            )
        )
        raise
    await send_to_hub(
        receipt_frame(
            transfer_id=claims.transfer_id,
            device_id=device_id,
            phase="completed",
            bytes_done=int(result["bytes_done"]),
            sha256=str(result["sha256"]),
            transport_used="direct",
        )
    )
    return result


async def run_direct_source(
    *,
    ticket: str,
    claims: TicketClaims,
    source_path: Path,
    device_id: str,
    host: str,
    port: int,
    send_to_hub: Callable[[dict[str, Any]], Any],
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Connect to peer TLS endpoint, stream file, emit completed receipt."""
    try:
        result = await asyncio.to_thread(
            send_file_over_tls,
            host=host,
            port=port,
            ticket=ticket,
            claims=claims,
            source_path=source_path,
            timeout=timeout,
        )
    except BaseException:
        await send_to_hub(
            receipt_frame(
                transfer_id=claims.transfer_id,
                device_id=device_id,
                phase="failed",
                transport_used="direct",
            )
        )
        raise
    await send_to_hub(
        receipt_frame(
            transfer_id=claims.transfer_id,
            device_id=device_id,
            phase="completed",
            bytes_done=int(result["bytes_done"]),
            sha256=str(result["sha256"]),
            transport_used="direct",
        )
    )
    return result


__all__ = [
    "handle_negotiate",
    "offer_frame",
    "peer_frame",
    "receipt_frame",
    "resolve_root_path",
    "run_direct_source",
    "run_direct_target",
]
