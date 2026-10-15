"""Bounded native file streams tied to one immutable execution context."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import stat
import threading
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, BinaryIO, cast

from octop.infra.devices.filesystem import NativeFileSystem

CHUNK = 1024 * 1024
IDLE_SECONDS = 600


def _identity(stream: BinaryIO) -> tuple[int, int, int, int]:
    value = os.fstat(stream.fileno())
    if not stat.S_ISREG(value.st_mode):
        raise ValueError("transfer requires a regular file")
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns


@dataclass
class _Stream:
    context: str
    kind: str
    path: Path
    target: Path
    stream: BinaryIO
    identity: tuple[int, int, int, int]
    size: int
    sha256: str
    temporary: Path | None = None
    expected_target: str | None = None
    offset: int = 0
    accessed: float = 0


class NativeTransfers:
    def __init__(self, state_dir: Path) -> None:
        self.manifest = state_dir / "native-transfers.json"
        self._streams: dict[str, _Stream] = {}
        self._completed: dict[str, tuple[str, dict[str, Any]]] = {}
        self._lock = threading.RLock()
        if self.manifest.exists():
            for item in json.loads(self.manifest.read_text(encoding="utf-8")).values():
                path = Path(item["temporary"])
                # Never remove a replacement or a link after a process restart.
                with contextlib.suppress(OSError):
                    info = path.lstat()
                    if (
                        path.name.startswith(".octop-native-")
                        and stat.S_ISREG(info.st_mode)
                        and [info.st_dev, info.st_ino] == item["identity"]
                    ):
                        path.unlink()
        self._persist()

    def _persist(self) -> None:
        from octop.infra.devices.executor import save_private_json

        save_private_json(
            self.manifest,
            {
                key: {"temporary": str(value.temporary), "identity": list(value.identity[:2])}
                for key, value in self._streams.items()
                if value.temporary is not None
            },
        )

    def _close(self, session: str) -> None:
        value = self._streams.pop(session, None)
        if value is None:
            return
        value.stream.close()
        if value.temporary is not None:
            with contextlib.suppress(FileNotFoundError):
                info = value.temporary.lstat()
                if stat.S_ISREG(info.st_mode) and (info.st_dev, info.st_ino) == value.identity[:2]:
                    value.temporary.unlink()
        self._persist()

    def reap(self) -> None:
        with self._lock:
            for session, value in list(self._streams.items()):
                if time.monotonic() - value.accessed > IDLE_SECONDS:
                    self._close(session)

    def close(self) -> None:
        with self._lock:
            for session in list(self._streams):
                self._close(session)

    def execute(
        self,
        action: str,
        params: dict[str, Any],
        directory: Path,
        commit: Callable[[], contextlib.AbstractContextManager[Any]],
    ) -> dict[str, Any]:
        with self._lock:
            self.reap()
            context = params.get("execution_context_id")
            if not isinstance(context, str) or not context:
                raise ValueError("transfer requires an execution context")
            kind = "upload" if action.startswith("fs.upload.") else "download"
            command = action.rsplit(".", 1)[-1]
            if command == "begin":
                if len(self._streams) >= 8:
                    raise ValueError("too many active file transfers")
                path = NativeFileSystem(directory).path(params.get("path", ""))
                target = path.resolve()
                stream: BinaryIO
                if kind == "download":
                    stream = target.open("rb")
                    try:
                        before = _identity(stream)
                        digest = hashlib.file_digest(stream, "sha256").hexdigest()
                        if before != _identity(stream):
                            raise ValueError("source changed during transfer preparation")
                        stream.seek(0)
                        value = _Stream(
                            context, kind, path, target, stream, before, before[2], digest
                        )
                    except BaseException:
                        stream.close()
                        raise
                else:
                    size, raw_digest = params.get("size"), params.get("sha256")
                    if type(size) is not int or not 0 <= size <= 64 * 1024**3:
                        raise ValueError("invalid transfer size (maximum 64 GiB)")
                    if (
                        not isinstance(raw_digest, str)
                        or len(raw_digest) != 64
                        or any(char not in "0123456789abcdef" for char in raw_digest)
                    ):
                        raise ValueError("invalid transfer sha256")
                    digest = raw_digest
                    expected = params.get("expected_sha256")
                    if target.exists() and (
                        not isinstance(expected, str) or NativeFileSystem.digest(target) != expected
                    ):
                        raise ValueError(
                            "destination exists or changed; supply its current checksum to replace"
                        )
                    temporary = target.parent / f".octop-native-{uuid.uuid4().hex}"
                    with commit():
                        fd = os.open(temporary, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
                    stream = os.fdopen(fd, "w+b")
                    value = _Stream(
                        context,
                        kind,
                        path,
                        target,
                        stream,
                        _identity(stream),
                        size,
                        digest,
                        temporary=temporary,
                        expected_target=expected,
                    )
                session = uuid.uuid4().hex
                value.accessed = time.monotonic()
                self._streams[session] = value
                self._persist()
                return {
                    "transfer_id": session,
                    "path": str(path),
                    "size": value.size,
                    "sha256": value.sha256,
                }
            requested_session = params.get("transfer_id")
            if not isinstance(requested_session, str):
                raise ValueError("invalid transfer id")
            session = requested_session
            completed = self._completed.get(session)
            if completed is not None and command in {"status", "commit"}:
                if completed[0] != context:
                    raise ValueError("transfer belongs to another execution context")
                return completed[1]
            current = self._streams.get(session)
            if current is None or current.kind != kind or current.context != context:
                raise ValueError("transfer unavailable in this execution context")
            value = current
            value.accessed = time.monotonic()
            if command in {"abort", "close"}:
                self._close(session)
                return {"closed": True}
            if command == "status":
                return {"status": "receiving", "bytes_done": value.offset, "size": value.size}
            if command == "chunk":
                offset = params.get("offset")
                if type(offset) is not int or not 0 <= offset <= value.size:
                    raise ValueError("invalid transfer offset")
                if kind == "download":
                    if _identity(value.stream) != value.identity:
                        raise ValueError("source changed during transfer")
                    value.stream.seek(offset)
                    data = value.stream.read(min(CHUNK, value.size - offset))
                    if _identity(value.stream) != value.identity:
                        raise ValueError("source changed during transfer")
                    return {
                        "data_b64": base64.b64encode(data).decode(),
                        "offset": offset,
                        "eof": offset + len(data) == value.size,
                        "size": value.size,
                    }
                encoded = params.get("data_b64")
                if not isinstance(encoded, str) or len(encoded) > ((CHUNK + 2) // 3) * 4:
                    raise ValueError("invalid transfer chunk")
                data = base64.b64decode(encoded, validate=True)
                if not data or offset != value.offset or offset + len(data) > value.size:
                    raise ValueError("unexpected transfer chunk or offset")
                with commit():
                    value.stream.write(data)
                    value.stream.flush()
                    value.offset += len(data)
                return {"bytes_done": value.offset}
            if command == "commit" and kind == "upload":
                if value.offset != value.size:
                    raise ValueError("transfer is incomplete")
                value.stream.flush()
                os.fsync(value.stream.fileno())
                value.stream.seek(0)
                digest = hashlib.file_digest(cast(Any, value.stream), "sha256").hexdigest()
                if digest != value.sha256:
                    raise ValueError("transfer checksum mismatch")
                with commit():
                    if value.path.resolve() != value.target:
                        raise ValueError("destination link changed during transfer")
                    assert value.temporary is not None
                    temporary_info = value.temporary.lstat()
                    if (
                        not stat.S_ISREG(temporary_info.st_mode)
                        or (temporary_info.st_dev, temporary_info.st_ino) != value.identity[:2]
                    ):
                        raise ValueError("transfer temporary file was replaced")
                    if value.target.exists():
                        if (
                            value.expected_target is None
                            or NativeFileSystem.digest(value.target) != value.expected_target
                        ):
                            raise ValueError("destination changed during transfer")
                    elif value.expected_target is not None:
                        raise ValueError("destination changed during transfer")
                    value.stream.close()
                    if value.expected_target is None:
                        os.link(value.temporary, value.target)
                        value.temporary.unlink()
                    else:
                        os.chmod(value.temporary, value.target.stat().st_mode)
                        os.replace(value.temporary, value.target)
                    result = {
                        "status": "completed",
                        "path": str(value.path),
                        "size": value.size,
                        "bytes_done": value.size,
                        "sha256": digest,
                    }
                    self._completed[session] = (context, result)
                    while len(self._completed) > 128:
                        self._completed.pop(next(iter(self._completed)))
                    self._streams.pop(session)
                    self._persist()
                return result
            raise ValueError("unsupported native transfer operation")
