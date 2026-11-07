"""Device-side helpers for 0044 transfer.negotiate / TLS data plane / receipts.

Validates ticket bindings, runs the peer TLS data plane, and builds receipt /
offer frames. Enrollment tokens must never be used as tickets.
"""

from __future__ import annotations

import asyncio
import contextlib
import ipaddress
import os
import socket
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

_LOOPBACK_NAMES = frozenset({"127.0.0.1", "::1", "localhost", "[::1]"})


def is_loopback_host(host: str) -> bool:
    """True when ``host`` is loopback / localhost (not routable across hosts)."""
    raw = str(host or "").strip().lower()
    if not raw:
        return False
    if raw in _LOOPBACK_NAMES:
        return True
    candidate = raw[1:-1] if raw.startswith("[") and raw.endswith("]") else raw
    with contextlib.suppress(ValueError):
        return ipaddress.ip_address(candidate).is_loopback
    return False


def _guess_advertise_ipv4() -> str | None:
    """Best-effort non-loopback IPv4 for LAN advertise (stdlib only)."""
    try:
        probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    except OSError:
        return None
    try:
        # No packets are sent; the kernel picks the outbound interface address.
        probe.connect(("8.8.8.8", 80))
        ip = probe.getsockname()[0]
    except OSError:
        return None
    finally:
        with contextlib.suppress(OSError):
            probe.close()
    if not ip or is_loopback_host(ip):
        return None
    return ip


def resolve_transfer_endpoints(
    *,
    listen_host: str | None = None,
    advertise_host: str | None = None,
    allow_loopback: bool = False,
) -> tuple[str, str]:
    """Resolve ``(listen_host, advertise_host)`` for peer TLS.

    - ``OCTOP_TRANSFER_LISTEN_HOST`` / ``OCTOP_TRANSFER_ADVERTISE_HOST`` override.
    - Default listen is ``0.0.0.0`` (all interfaces).
    - Default advertise is the first non-loopback IPv4, never ``127.0.0.1`` /
      ``::1`` unless ``allow_loopback=True`` (same-host dual-executor tests only).
    """
    env_listen = (os.environ.get("OCTOP_TRANSFER_LISTEN_HOST") or "").strip() or None
    env_adv = (os.environ.get("OCTOP_TRANSFER_ADVERTISE_HOST") or "").strip() or None
    listen = (listen_host or env_listen or "0.0.0.0").strip()
    advertise = (advertise_host or env_adv or _guess_advertise_ipv4() or "").strip()
    if not advertise:
        if allow_loopback:
            advertise = "127.0.0.1"
        else:
            raise ValueError("TRANSFER_DIRECT_UNAVAILABLE")
    if is_loopback_host(advertise) and not allow_loopback:
        raise ValueError("TRANSFER_DIRECT_UNAVAILABLE")
    return listen, advertise


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
    listen_host: str | None = None,
    advertise_host: str | None = None,
    allow_loopback: bool = False,
    host: str | None = None,
    timeout: float = 30.0,
) -> dict[str, Any]:
    """Listen on TLS, publish offer to Hub, receive file, emit completed receipt.

    ``host`` is a legacy alias for both listen and advertise (same-host tests).
    Production callers should omit ``host`` so advertise resolves to a routable
    non-loopback address; loopback is refused unless ``allow_loopback=True``.
    """
    if host is not None and listen_host is None and advertise_host is None:
        listen_host = host
        advertise_host = host
        allow_loopback = allow_loopback or is_loopback_host(host)
    listen, advertise = resolve_transfer_endpoints(
        listen_host=listen_host,
        advertise_host=advertise_host,
        allow_loopback=allow_loopback,
    )
    listener = PeerTlsListener(
        ticket=ticket,
        claims=claims,
        dest_path=dest_path,
        overwrite=overwrite,
        host=listen,
        advertise_host=advertise,
        timeout=timeout,
    )
    offered_host, port = await asyncio.to_thread(listener.start)
    await send_to_hub(
        offer_frame(
            transfer_id=claims.transfer_id,
            device_id=device_id,
            host=offered_host,
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
    "is_loopback_host",
    "offer_frame",
    "peer_frame",
    "receipt_frame",
    "resolve_root_path",
    "resolve_transfer_endpoints",
    "run_direct_source",
    "run_direct_target",
]
