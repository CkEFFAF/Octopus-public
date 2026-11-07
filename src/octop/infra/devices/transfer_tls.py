"""0044 peer TLS data plane (LAN-direct).

Encrypts the socket with ephemeral self-signed certificates (no plaintext TCP).
Application-layer HMAC binds the session to the Hub-issued transfer ticket so
peers cannot swap transfer_id / size / sha256 / device ids. File bytes stream
peer-to-peer and never transit the Hub control plane.
"""

from __future__ import annotations

import contextlib
import hashlib
import hmac
import json
import os
import socket
import ssl
import struct
import tempfile
import threading
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from octop.infra.devices.transfer_session import TicketClaims, parse_ticket

CHUNK = 64 * 1024
_HEADER = struct.Struct("!I")
_DEFAULT_TIMEOUT = 30.0


def ticket_proof(ticket: str, *, role: str, transfer_id: str) -> str:
    """HMAC proof that the peer holds the opaque ticket for this role."""
    material = f"octop-xfer-v1|{role}|{transfer_id}".encode()
    return hmac.new(ticket.encode("utf-8"), material, hashlib.sha256).hexdigest()


def _ephemeral_cert() -> tuple[bytes, bytes]:
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    subject = issuer = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, f"octop-xfer-{uuid.uuid4().hex[:12]}")]
    )
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(hours=1))
        .sign(key, hashes.SHA256())
    )
    cert_pem = cert.public_bytes(serialization.Encoding.PEM)
    key_pem = key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.TraditionalOpenSSL,
        serialization.NoEncryption(),
    )
    return cert_pem, key_pem


def _ssl_context(*, server: bool) -> ssl.SSLContext:
    cert_pem, key_pem = _ephemeral_cert()
    ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER if server else ssl.PROTOCOL_TLS_CLIENT)
    ctx.minimum_version = ssl.TLSVersion.TLSv1_2
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    cert_file = tempfile.NamedTemporaryFile(delete=False)
    key_file = tempfile.NamedTemporaryFile(delete=False)
    try:
        cert_file.write(cert_pem)
        key_file.write(key_pem)
        cert_file.close()
        key_file.close()
        ctx.load_cert_chain(cert_file.name, key_file.name)
    finally:
        for path in (cert_file.name, key_file.name):
            with contextlib.suppress(OSError):
                os.unlink(path)
    return ctx


class _BufSock:
    """Tiny buffered reader so JSON control lines and binary chunks coexist."""

    def __init__(self, conn: ssl.SSLSocket) -> None:
        self.conn = conn
        self.buf = bytearray()

    def sendall(self, data: bytes) -> None:
        self.conn.sendall(data)

    def recv_exact(self, n: int) -> bytes:
        while len(self.buf) < n:
            chunk = self.conn.recv(max(CHUNK, n - len(self.buf)))
            if not chunk:
                raise ValueError("TRANSFER_IO")
            self.buf.extend(chunk)
        out = bytes(self.buf[:n])
        del self.buf[:n]
        return out

    def recv_json(self, *, timeout: float) -> dict[str, Any]:
        self.conn.settimeout(timeout)
        while b"\n" not in self.buf:
            chunk = self.conn.recv(4096)
            if not chunk:
                raise ValueError("TRANSFER_IO")
            self.buf.extend(chunk)
            if len(self.buf) > 64 * 1024:
                raise ValueError("TRANSFER_IO")
        line, _, rest = bytes(self.buf).partition(b"\n")
        self.buf = bytearray(rest)
        raw = json.loads(line.decode("utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("TRANSFER_IO")
        return raw

    def send_json(self, payload: dict[str, Any]) -> None:
        raw = (json.dumps(payload, separators=(",", ":"), ensure_ascii=False) + "\n").encode(
            "utf-8"
        )
        if len(raw) > 64 * 1024:
            raise ValueError("TRANSFER_IO")
        self.sendall(raw)

    def close(self) -> None:
        self.conn.close()


def _verify_hello(
    msg: dict[str, Any],
    *,
    expect_role: str,
    ticket: str,
    claims: TicketClaims,
) -> None:
    if msg.get("type") != "xfer.hello":
        raise ValueError("TRANSFER_PEER_MISMATCH")
    if str(msg.get("role") or "") != expect_role:
        raise ValueError("TRANSFER_PEER_MISMATCH")
    if str(msg.get("transfer_id") or "") != claims.transfer_id:
        raise ValueError("TRANSFER_PEER_MISMATCH")
    if int(msg.get("size") or -1) != claims.size:
        raise ValueError("TRANSFER_PEER_MISMATCH")
    if str(msg.get("sha256") or "").lower() != claims.sha256:
        raise ValueError("TRANSFER_PEER_MISMATCH")
    expected = ticket_proof(ticket, role=expect_role, transfer_id=claims.transfer_id)
    if not hmac.compare_digest(str(msg.get("proof") or ""), expected):
        raise ValueError("TRANSFER_TICKET_INVALID")


def _hello_payload(*, role: str, ticket: str, claims: TicketClaims) -> dict[str, Any]:
    return {
        "type": "xfer.hello",
        "role": role,
        "transfer_id": claims.transfer_id,
        "size": claims.size,
        "sha256": claims.sha256,
        "proof": ticket_proof(ticket, role=role, transfer_id=claims.transfer_id),
        "schema_version": 1,
    }


def _atomic_commit(temporary: Path, target: Path, *, overwrite: bool) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and not overwrite:
        raise ValueError("TRANSFER_TARGET_EXISTS")
    if overwrite and target.exists():
        os.replace(temporary, target)
    else:
        os.link(temporary, target)
        temporary.unlink()


class PeerTlsListener:
    """Target-side listener: accept one peer, receive file, verify, commit."""

    def __init__(
        self,
        *,
        ticket: str,
        claims: TicketClaims,
        dest_path: Path,
        overwrite: bool = False,
        host: str = "127.0.0.1",
        timeout: float = _DEFAULT_TIMEOUT,
    ) -> None:
        self.ticket = ticket
        self.claims = claims
        self.dest_path = dest_path
        self.overwrite = overwrite
        self.host = host
        self.timeout = timeout
        self.port: int | None = None
        self._sock: socket.socket | None = None
        self._error: BaseException | None = None
        self._result: dict[str, Any] | None = None
        self._thread: threading.Thread | None = None

    def start(self) -> tuple[str, int]:
        ctx = _ssl_context(server=True)
        raw = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        raw.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        raw.bind((self.host, 0))
        raw.listen(1)
        raw.settimeout(self.timeout)
        self.port = int(raw.getsockname()[1])
        self._sock = raw
        self._thread = threading.Thread(target=self._run, args=(ctx,), daemon=True)
        self._thread.start()
        return self.host, self.port

    def _run(self, ctx: ssl.SSLContext) -> None:
        assert self._sock is not None
        temporary: Path | None = None
        try:
            client, _addr = self._sock.accept()
            wrapped = ctx.wrap_socket(client, server_side=True)
            conn = _BufSock(wrapped)
            try:
                peer_hello = conn.recv_json(timeout=self.timeout)
                _verify_hello(
                    peer_hello, expect_role="source", ticket=self.ticket, claims=self.claims
                )
                conn.send_json(
                    _hello_payload(role="target", ticket=self.ticket, claims=self.claims)
                )
                ack = conn.recv_json(timeout=self.timeout)
                if ack.get("type") != "xfer.begin":
                    raise ValueError("TRANSFER_IO")
                temporary = self.dest_path.parent / f".octop-xfer-{uuid.uuid4().hex}"
                self.dest_path.parent.mkdir(parents=True, exist_ok=True)
                digest = hashlib.sha256()
                received = 0
                with temporary.open("wb") as out:
                    while received < self.claims.size:
                        header = conn.recv_exact(_HEADER.size)
                        (length,) = _HEADER.unpack(header)
                        if length <= 0 or received + length > self.claims.size:
                            raise ValueError("TRANSFER_IO")
                        data = conn.recv_exact(length)
                        out.write(data)
                        digest.update(data)
                        received += length
                    out.flush()
                    os.fsync(out.fileno())
                got = digest.hexdigest()
                if received != self.claims.size or got != self.claims.sha256:
                    raise ValueError("TRANSFER_SOURCE_CHANGED")
                _atomic_commit(temporary, self.dest_path, overwrite=self.overwrite)
                temporary = None
                conn.send_json(
                    {
                        "type": "xfer.done",
                        "transfer_id": self.claims.transfer_id,
                        "bytes_done": received,
                        "sha256": got,
                    }
                )
                self._result = {
                    "bytes_done": received,
                    "sha256": got,
                    "transport_used": "direct",
                    "path": str(self.dest_path),
                }
            finally:
                conn.close()
        except BaseException as exc:
            self._error = exc
            if temporary is not None:
                with contextlib.suppress(OSError):
                    temporary.unlink()
        finally:
            with contextlib.suppress(OSError):
                self._sock.close()

    def wait(self, timeout: float | None = None) -> dict[str, Any]:
        if self._thread is None:
            raise RuntimeError("listener not started")
        self._thread.join(timeout if timeout is not None else self.timeout + 5)
        if self._thread.is_alive():
            raise TimeoutError("direct receive timed out")
        if self._error is not None:
            raise self._error
        if self._result is None:
            raise ValueError("TRANSFER_IO")
        return self._result

    def close(self) -> None:
        if self._sock is not None:
            with contextlib.suppress(OSError):
                self._sock.close()


def send_file_over_tls(
    *,
    host: str,
    port: int,
    ticket: str,
    claims: TicketClaims,
    source_path: Path,
    timeout: float = _DEFAULT_TIMEOUT,
) -> dict[str, Any]:
    """Source-side: TLS connect, authenticate with ticket, stream file bytes."""
    if not source_path.is_file():
        raise ValueError("TRANSFER_IO")
    size = source_path.stat().st_size
    if size != claims.size:
        raise ValueError("TRANSFER_SOURCE_CHANGED")
    ctx = _ssl_context(server=False)
    raw = socket.create_connection((host, port), timeout=timeout)
    wrapped = ctx.wrap_socket(raw, server_hostname=host)
    conn = _BufSock(wrapped)
    try:
        conn.send_json(_hello_payload(role="source", ticket=ticket, claims=claims))
        peer_hello = conn.recv_json(timeout=timeout)
        _verify_hello(peer_hello, expect_role="target", ticket=ticket, claims=claims)
        conn.send_json({"type": "xfer.begin", "transfer_id": claims.transfer_id})
        digest = hashlib.sha256()
        sent = 0
        with source_path.open("rb") as src:
            while sent < claims.size:
                data = src.read(min(CHUNK, claims.size - sent))
                if not data:
                    raise ValueError("TRANSFER_SOURCE_CHANGED")
                digest.update(data)
                conn.sendall(_HEADER.pack(len(data)) + data)
                sent += len(data)
        got = digest.hexdigest()
        if got != claims.sha256:
            raise ValueError("TRANSFER_SOURCE_CHANGED")
        done = conn.recv_json(timeout=timeout)
        if done.get("type") != "xfer.done" or str(done.get("sha256") or "").lower() != got:
            raise ValueError("TRANSFER_IO")
        return {
            "bytes_done": sent,
            "sha256": got,
            "transport_used": "direct",
            "path": str(source_path),
        }
    finally:
        conn.close()


def claims_from_ticket(ticket: str) -> TicketClaims:
    return parse_ticket(ticket)


__all__ = [
    "PeerTlsListener",
    "claims_from_ticket",
    "send_file_over_tls",
    "ticket_proof",
]
