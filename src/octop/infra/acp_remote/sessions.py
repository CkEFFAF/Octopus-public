"""Persist ACP session ↔ remote work-item / thread mapping."""

from __future__ import annotations

import contextlib
import json
import os
from pathlib import Path
from typing import Any


def default_store_path() -> Path:
    home = Path(os.environ.get("OCTOP_HOME") or Path.home() / ".octop")
    return home / "acp-remote" / "sessions.json"


class SessionStore:
    def __init__(self, path: Path | None = None) -> None:
        self.path = path or default_store_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._data: dict[str, dict[str, Any]] = {}
        self._load()

    def _load(self) -> None:
        if not self.path.exists():
            self._data = {}
            return
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            self._data = raw if isinstance(raw, dict) else {}
        except (OSError, json.JSONDecodeError):
            self._data = {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._data, indent=2, sort_keys=True), encoding="utf-8")
        tmp.replace(self.path)
        with contextlib.suppress(OSError):
            os.chmod(self.path, 0o600)

    def get(self, session_id: str) -> dict[str, Any] | None:
        row = self._data.get(session_id)
        return dict(row) if row else None

    def put(self, session_id: str, values: dict[str, Any]) -> None:
        self._data[session_id] = dict(values)
        self._save()

    def delete(self, session_id: str) -> None:
        if session_id in self._data:
            del self._data[session_id]
            self._save()
