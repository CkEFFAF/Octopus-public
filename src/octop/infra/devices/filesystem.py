"""Native device paths: working directory is a default, not a permission mount."""

from __future__ import annotations

import base64
import contextlib
import hashlib
import json
import os
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any


class NativeFileSystem:
    def __init__(
        self,
        working_dir: Path,
        *,
        commit: Callable[[], contextlib.AbstractContextManager[Any]] = contextlib.nullcontext,
    ) -> None:
        self.working_dir = working_dir
        self.commit = commit

    def path(self, value: str) -> Path:
        if not isinstance(value, str) or "\x00" in value:
            raise ValueError("invalid device path")
        path = Path(value).expanduser()
        return path if path.is_absolute() else self.working_dir / path

    @staticmethod
    def digest(path: Path) -> str:
        with path.open("rb") as stream:
            return hashlib.file_digest(stream, "sha256").hexdigest()

    def execute(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        path = self.path(params.get("path", "."))
        if action in {"fs.glob", "fs.grep"}:
            return self.search(action, path, params)
        if action == "fs.edit":
            old, new = params.get("old_string"), params.get("new_string")
            if not isinstance(old, str) or not old or not isinstance(new, str):
                raise ValueError("invalid edit text")
            with path.open("rb") as stream:
                original = stream.read(1048577)
            if len(original) > 1048576:
                raise ValueError("file exceeds inline edit limit; use a device command")
            text = original.decode("utf-8")
            occurrences = text.count(old)
            if not occurrences or (occurrences > 1 and params.get("replace_all") is not True):
                raise ValueError("edit text is absent or matches multiple locations")
            changed = text.replace(
                old, new, occurrences if params.get("replace_all") is True else 1
            )
            result = self.execute(
                "fs.write",
                {
                    "path": str(path),
                    "expected_sha256": hashlib.sha256(original).hexdigest(),
                    "data_b64": base64.b64encode(changed.encode()).decode(),
                },
            )
            return {**result, "occurrences": occurrences}
        if action == "fs.list":
            entries = []
            offset, limit = params.get("offset", 0), params.get("limit", 500)
            if (
                type(offset) is not int
                or offset < 0
                or type(limit) is not int
                or not 1 <= limit <= 500
            ):
                raise ValueError("invalid directory page")
            candidates = sorted(path.iterdir(), key=lambda p: (not p.is_dir(), p.name.casefold()))
            for item in candidates[offset : offset + limit]:
                try:
                    info = item.stat()
                    entries.append(
                        {
                            "name": item.name,
                            "path": str(item),
                            "is_dir": item.is_dir(),
                            "is_link": item.is_symlink(),
                            "size": info.st_size,
                        }
                    )
                except OSError:
                    entries.append({"name": item.name, "path": str(item), "unavailable": True})
            return {
                "path": str(path),
                "entries": entries,
                "next_offset": offset + limit if offset + limit < len(candidates) else None,
            }
        if action == "fs.stat":
            info = path.stat()
            hashable = not path.is_dir() and info.st_size <= 1048576
            return {
                "path": str(path),
                "size": info.st_size,
                "is_dir": path.is_dir(),
                "mtime_ns": info.st_mtime_ns,
                "sha256": self.digest(path) if hashable else None,
                "hash_omitted": not path.is_dir() and not hashable,
            }
        if action == "fs.read":
            offset, length = params.get("offset", 0), params.get("length", 1048576)
            if (
                type(offset) is not int
                or offset < 0
                or type(length) is not int
                or not 1 <= length <= 1048576
            ):
                raise ValueError("invalid device read range")
            with path.open("rb") as stream:
                stream.seek(offset)
                data = stream.read(length)
                size = os.fstat(stream.fileno()).st_size
            return {
                "path": str(path),
                "data_b64": base64.b64encode(data).decode(),
                "size": size,
                "offset": offset,
                "eof": offset + len(data) >= size,
            }
        if action == "fs.write":
            requested_path = path
            # Normal file I/O follows the final symlink. Atomic replacement must
            # address its target as well, preserving the caller's link itself.
            if path.is_symlink():
                path = path.resolve()
            encoded = params.get("data_b64")
            if not isinstance(encoded, str) or len(encoded) > 1400000:
                raise ValueError("invalid device write payload")
            data = base64.b64decode(encoded, validate=True)
            expected = params.get("expected_sha256")
            if params.get("create_only") is True and requested_path.exists():
                raise ValueError("file already exists; use edit")
            if expected is not None and (not path.is_file() or self.digest(path) != expected):
                raise ValueError("file changed since it was read")
            fd, temporary = tempfile.mkstemp(prefix=".octop-write-", dir=path.parent)
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                    stream.flush()
                    os.fsync(stream.fileno())
                if path.exists():
                    os.chmod(temporary, path.stat().st_mode)
                with self.commit():
                    if requested_path.is_symlink() and requested_path.resolve() != path:
                        raise ValueError("file link changed since it was read")
                    if expected is not None and self.digest(path) != expected:
                        raise ValueError("file changed since it was read")
                    if params.get("create_only") is True:
                        os.link(temporary, path)
                    else:
                        os.replace(temporary, path)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
            return {
                "path": str(requested_path),
                "size": len(data),
                "sha256": hashlib.sha256(data).hexdigest(),
            }
        if action == "fs.mkdir":
            with self.commit():
                path.mkdir(parents=params.get("parents") is True, exist_ok=True)
        elif action == "fs.move":
            destination = self.path(params["destination"])
            if destination.exists():
                raise ValueError("destination already exists")
            with self.commit():
                path.rename(destination)
            return {"path": str(destination)}
        elif action == "fs.remove":
            if path.is_dir() and not path.is_symlink() and params.get("recursive") is True:
                # Check cancellation and current policy before each deletion.
                for directory, folders, files in os.walk(path, topdown=False, followlinks=False):
                    for name in files + folders:
                        item = Path(directory) / name
                        with self.commit():
                            if item.is_symlink() or not item.is_dir():
                                item.unlink()
                            else:
                                item.rmdir()
                with self.commit():
                    path.rmdir()
            else:
                with self.commit():
                    if path.is_symlink() or not path.is_dir():
                        path.unlink()
                    else:
                        path.rmdir()
        else:
            raise ValueError("unsupported native filesystem action")
        return {"path": str(path)}

    def search(self, action: str, path: Path, params: dict[str, Any]) -> dict[str, Any]:
        pattern = params.get("pattern", "*")
        if not isinstance(pattern, str):
            raise ValueError("invalid search pattern")
        candidates = (
            [path]
            if path.is_file()
            else path.glob(pattern if action == "fs.glob" else params.get("glob") or "**/*")
        )
        items: list[dict[str, Any]] = []
        truncated = False
        output_bytes = 0
        max_count = params.get("max_count")
        if max_count is not None and (type(max_count) is not int or max_count < 0):
            raise ValueError("invalid per-file match limit")
        deadline = time.monotonic() + 10
        for visited, item in enumerate(candidates):
            if visited >= 10000 or time.monotonic() >= deadline or len(items) >= 1000:
                truncated = True
                break
            try:
                if action == "fs.glob":
                    items.append(
                        {"path": str(item), "is_dir": item.is_dir(), "size": item.stat().st_size}
                    )
                elif item.is_file():
                    if item.stat().st_size > 1048576:
                        truncated = True
                        continue
                    matched = 0
                    for number, line in enumerate(item.read_text(encoding="utf-8").splitlines(), 1):
                        if max_count is not None and matched >= max_count:
                            break
                        if pattern in line:
                            items.append(
                                {"path": str(item), "line_number": number, "line": line[:5000]}
                            )
                            matched += 1
                            output_bytes += len(
                                json.dumps(items[-1], ensure_ascii=False).encode("utf-8")
                            )
                        if output_bytes >= 524288:
                            truncated = True
                            break
                        if len(items) >= 1000:
                            truncated = True
                            break
            except (OSError, UnicodeError):
                truncated = True
            if output_bytes >= 524288:
                break
        return {"entries" if action == "fs.glob" else "matches": items, "truncated": truncated}
