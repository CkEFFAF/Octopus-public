"""Device-local confirmations for background and headless execution clients."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import json
import math
import os
import threading
import time
import uuid
from pathlib import Path
from typing import Any

from octop.i18n import DEFAULT_LOCALE, tr
from octop.infra.devices.executor import _reject_links, private_state_dir, save_private_json

_window_lock = threading.Lock()


def _text(value: object) -> str:
    return "".join(c if c.isprintable() or c == "\n" else f"\\u{ord(c):04x}" for c in str(value))


def _native_confirm(details: str, deadline: float, cancelled: threading.Event) -> bool | None:
    # All Tk calls belong to this worker; never block the connection reader.
    if not _window_lock.acquire(blocking=False):
        return None
    root: Any = None
    accepted: bool | None = False
    try:
        import tkinter as tk
        from tkinter import ttk

        root = tk.Tk()
        root.title(tr("desktop.consent.title", DEFAULT_LOCALE))
        root.resizable(False, False)
        root.attributes("-topmost", True)
        panel = ttk.Frame(root, padding=24)
        panel.pack(fill="both", expand=True)
        content = ttk.Frame(panel)
        content.pack(fill="both", expand=True)
        text = tk.Text(content, width=72, height=18, wrap="word", padx=10, pady=10)
        scroll = ttk.Scrollbar(content, command=text.yview)
        text.configure(yscrollcommand=scroll.set)
        scroll.pack(side="right", fill="y")
        text.pack(side="left", fill="both", expand=True)
        text.insert("1.0", details)
        text.configure(state="disabled")
        countdown = ttk.Label(panel)
        countdown.pack(anchor="w", pady=(16, 12))
        buttons = ttk.Frame(panel)
        buttons.pack(fill="x")

        def finish(allow: bool = False) -> None:
            nonlocal accepted
            accepted = allow and not cancelled.is_set() and time.time() < deadline
            root.destroy()

        reject = ttk.Button(
            buttons, text=tr("desktop.consent.reject", DEFAULT_LOCALE), command=finish
        )
        reject.pack(side="right")
        ttk.Button(
            buttons,
            text=tr("desktop.consent.allow", DEFAULT_LOCALE),
            command=lambda: finish(True),
        ).pack(side="right", padx=(0, 12))
        root.protocol("WM_DELETE_WINDOW", finish)
        root.bind("<Escape>", lambda _event: finish())
        reject.focus_set()

        def tick() -> None:
            remaining = math.ceil(deadline - time.time())
            if cancelled.is_set() or remaining <= 0:
                finish()
                return
            countdown.config(text=tr("desktop.consent.timeout", DEFAULT_LOCALE, seconds=remaining))
            root.after(200, tick)

        root.after(0, tick)
        root.mainloop()
    except Exception:
        # Missing Tk / interactive desktop must never imply consent.
        accepted = None
    finally:
        if root is not None:
            with contextlib.suppress(Exception):
                root.destroy()
        _window_lock.release()
    return accepted


def pending_consents(state_dir: Path) -> list[dict[str, Any]]:
    inbox = state_dir / "consents"
    _reject_links(inbox)
    if not inbox.exists():
        return []
    result = []
    for path in inbox.glob("*.request.json"):
        _reject_links(path)
        item = json.loads(path.read_text(encoding="utf-8"))
        if item["expires_at"] > time.time():
            result.append(item)
    return result


def decide_consent(state_dir: Path, request_id: str, *, accept: bool) -> None:
    key = hashlib.sha256(request_id.encode()).hexdigest()
    inbox = state_dir / "consents"
    request = inbox / f"{key}.request.json"
    _reject_links(request)
    item = json.loads(request.read_text(encoding="utf-8"))
    if item["request_id"] != request_id or item["expires_at"] <= time.time():
        raise ValueError("confirmation expired")
    save_private_json(
        inbox / f"{key}.decision.json",
        {"nonce": item["nonce"], "accept": accept},
    )


async def confirm(
    state_dir: Path, *, request_id: str, server_url: str, details: str, expires_at: object
) -> bool:
    if not isinstance(expires_at, (int, float)) or not math.isfinite(expires_at):
        return False
    deadline = min(float(expires_at), time.time() + 72 * 3600)
    if deadline <= time.time():
        return False
    inbox = private_state_dir(state_dir / "consents")
    key = hashlib.sha256(request_id.encode()).hexdigest()
    request_path = inbox / f"{key}.request.json"
    decision_path = inbox / f"{key}.decision.json"
    nonce = uuid.uuid4().hex
    summary = _text(server_url) + "\n\n" + _text(details)
    save_private_json(
        request_path,
        {"request_id": request_id, "nonce": nonce, "details": summary, "expires_at": deadline},
    )
    cancelled = threading.Event()
    window: asyncio.Future[bool | None] | None = None
    if os.name == "nt" or os.environ.get("DISPLAY"):
        window = asyncio.get_running_loop().run_in_executor(
            None, _native_confirm, summary, min(deadline, time.time() + 60), cancelled
        )
    try:
        while time.time() < deadline:
            if window is not None and window.done():
                result = window.result()
                if result is not None:
                    return result is True and time.time() < deadline
                window = None  # No interactive desktop; retain the local CLI inbox.
            _reject_links(decision_path)
            if decision_path.exists():
                choice = json.loads(decision_path.read_text(encoding="utf-8"))
                return choice.get("nonce") == nonce and choice.get("accept") is True
            await asyncio.sleep(0.2)
        return False
    finally:
        cancelled.set()
        for path in (request_path, decision_path):
            _reject_links(path)
            path.unlink(missing_ok=True)
