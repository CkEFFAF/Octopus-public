"""0044 wire helpers: negotiate / offer / peer / receipt frame shapes (control plane)."""

from __future__ import annotations

from typing import Any


def negotiate_frame(
    *,
    transfer_id: str,
    role: str,
    peer_device_id: str,
    ticket: str,
    ticket_expires_at: float,
    size: int,
    sha256: str,
    path_scope: dict[str, str],
    preferred_transport: str,
) -> dict[str, Any]:
    return {
        "type": "transfer.negotiate",
        "transfer_id": transfer_id,
        "role": role,
        "peer_device_id": peer_device_id,
        "ticket": ticket,
        "ticket_expires_at": ticket_expires_at,
        "size": size,
        "sha256": sha256,
        "path_scope": path_scope,
        "preferred_transport": preferred_transport,
        "listen": {"mode": "lan_tls", "port_hint": None},
        "schema_version": 1,
    }


def offer_frame(
    *,
    transfer_id: str,
    device_id: str,
    host: str,
    port: int,
) -> dict[str, Any]:
    """Target → Hub: TLS listen endpoint for LAN-direct (control plane only)."""
    return {
        "type": "transfer.offer",
        "transfer_id": transfer_id,
        "device_id": device_id,
        "host": host,
        "port": int(port),
        "schema_version": 1,
    }


def peer_frame(
    *,
    transfer_id: str,
    host: str,
    port: int,
) -> dict[str, Any]:
    """Hub → source: peer TLS endpoint relayed from target offer."""
    return {
        "type": "transfer.peer",
        "transfer_id": transfer_id,
        "host": host,
        "port": int(port),
        "schema_version": 1,
    }


def cancel_frame(transfer_id: str) -> dict[str, Any]:
    return {"type": "transfer.cancel", "transfer_id": transfer_id, "schema_version": 1}


def validate_receipt_frame(frame: dict[str, Any]) -> dict[str, Any]:
    transfer_id = frame.get("transfer_id")
    device_id = frame.get("device_id")
    phase = frame.get("phase")
    if not isinstance(transfer_id, str) or not transfer_id:
        raise ValueError("invalid transfer.receipt")
    if not isinstance(device_id, str) or not device_id:
        raise ValueError("invalid transfer.receipt")
    if phase not in {
        "negotiating",
        "transferring",
        "verifying",
        "completed",
        "failed",
        "cancelled",
    }:
        raise ValueError("invalid transfer.receipt")
    out: dict[str, Any] = {
        "transfer_id": transfer_id,
        "device_id": device_id,
        "phase": phase,
        "bytes_done": frame.get("bytes_done"),
        "sha256": frame.get("sha256"),
        "transport_used": frame.get("transport_used"),
        "schema_version": int(frame.get("schema_version") or 1),
    }
    return out


def validate_offer_frame(frame: dict[str, Any]) -> dict[str, Any]:
    transfer_id = frame.get("transfer_id")
    device_id = frame.get("device_id")
    host = frame.get("host")
    port = frame.get("port")
    if not isinstance(transfer_id, str) or not transfer_id:
        raise ValueError("invalid transfer.offer")
    if not isinstance(device_id, str) or not device_id:
        raise ValueError("invalid transfer.offer")
    if not isinstance(host, str) or not host:
        raise ValueError("invalid transfer.offer")
    if type(port) is not int or not 1 <= port <= 65535:
        raise ValueError("invalid transfer.offer")
    return {
        "transfer_id": transfer_id,
        "device_id": device_id,
        "host": host,
        "port": port,
        "schema_version": int(frame.get("schema_version") or 1),
    }


__all__ = [
    "cancel_frame",
    "negotiate_frame",
    "offer_frame",
    "peer_frame",
    "validate_offer_frame",
    "validate_receipt_frame",
]
