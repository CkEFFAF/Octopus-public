"""0006 first-run wizard helpers: default server, UU enroll, optional Tk UI."""

from __future__ import annotations

import asyncio
import platform
from pathlib import Path
from typing import Any, Callable

from octop.infra.devices.client import account_login, validate_server_url
from octop.infra.devices.executor import DeviceExecutionError
from octop.infra.devices.network import DeviceNetwork, validate_relocation_url
from octop.infra.devices.protocol import (
    is_transition_insecure_allowed,
    resolve_default_device_server,
)


def resolve_server_url(server: str | None, *, allow_insecure: bool = False) -> str:
    """Normalize server URL; empty/None uses env override or product default."""
    return resolve_server_and_insecure(server, allow_insecure=allow_insecure)[0]


def resolve_server_and_insecure(
    server: str | None, *, allow_insecure: bool = False
) -> tuple[str, bool]:
    """Return (url, allow_insecure); whitelist hub auto-opts insecure (0010)."""
    raw = (server or "").strip() or resolve_default_device_server()
    url = validate_relocation_url(raw)
    insecure = bool(allow_insecure) or is_transition_insecure_allowed(url)
    validate_server_url(url, allow_insecure=insecure)
    return url, insecure


def has_configured_controller(state: Path) -> bool:
    return any(item.get("status") == "configured" for item in DeviceNetwork(state).controllers())


async def _add_default_controller(
    state: Path,
    *,
    server: str,
    name: str,
    allow_insecure: bool = False,
    access_key: str | None = None,
    account_token: str | None = None,
    pairing_code: str = "",
) -> dict[str, Any]:
    """Register-first enroll with 0005 REQ-007 local consent; no roots required."""
    url = resolve_server_url(server, allow_insecure=allow_insecure)
    return await DeviceNetwork(state).add_controller(
        url,
        pairing_code,
        name,
        ["files_read"],
        [],
        desktop_enabled=True,
        control_enabled=True,
        command_enabled=False,
        acp_enabled=False,
        allow_insecure=allow_insecure,
        access_key=access_key,
        account_token=account_token,
    )


def enroll_with_account(
    state: Path,
    *,
    server: str,
    username: str,
    password: str,
    name: str | None = None,
    allow_insecure: bool = False,
    account_token: str | None = None,
) -> dict[str, Any]:
    """Register-first enroll via 0004 Bearer JWT; password never written to device-state."""
    url, insecure = resolve_server_and_insecure(server, allow_insecure=allow_insecure)
    token = account_token
    if not token:
        if not username or not password:
            raise DeviceExecutionError("account username and password are required")
        token = account_login(url, username, password, allow_insecure=insecure)
    return asyncio.run(
        _add_default_controller(
            state,
            server=url,
            name=name or platform.node(),
            allow_insecure=insecure,
            account_token=token,
        )
    )


def enroll_with_credential(
    state: Path,
    *,
    server: str,
    credential: str,
    name: str | None = None,
    allow_insecure: bool = False,
) -> dict[str, Any]:
    """Advanced path: pairing code or oak_ access key, still register-first defaults."""
    credential = credential.strip()
    if not credential:
        raise DeviceExecutionError("pairing code or access key is required")
    access_key = credential if credential.startswith("oak_") else None
    pair_code = "" if access_key else credential
    url, insecure = resolve_server_and_insecure(server, allow_insecure=allow_insecure)
    return asyncio.run(
        _add_default_controller(
            state,
            server=url,
            name=name or platform.node(),
            allow_insecure=insecure,
            access_key=access_key,
            pairing_code=pair_code,
        )
    )


def gui_available() -> bool:
    if platform.system() == "Windows":
        return True
    import os

    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


def run_tk_first_run(
    state: Path,
    *,
    server: str | None = None,
    on_success: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any] | None:
    """Blocking Tk first-run form. Returns the added controller or None if cancelled."""
    import tkinter as tk
    from tkinter import messagebox, ttk

    result: dict[str, Any] = {"controller": None, "cancelled": True}
    root = tk.Tk()
    root.title("Octop device join")
    root.resizable(False, False)

    frm = ttk.Frame(root, padding=16)
    frm.grid(row=0, column=0, sticky="nsew")

    ttk.Label(frm, text="Server URL").grid(row=0, column=0, sticky="w")
    server_var = tk.StringVar(
        value=(server or "").strip() or resolve_default_device_server()
    )
    ttk.Entry(frm, textvariable=server_var, width=42).grid(row=0, column=1, sticky="ew", pady=4)

    ttk.Label(frm, text="Username").grid(row=1, column=0, sticky="w")
    user_var = tk.StringVar()
    ttk.Entry(frm, textvariable=user_var, width=42).grid(row=1, column=1, sticky="ew", pady=4)

    ttk.Label(frm, text="Password").grid(row=2, column=0, sticky="w")
    pass_var = tk.StringVar()
    ttk.Entry(frm, textvariable=pass_var, show="*", width=42).grid(
        row=2, column=1, sticky="ew", pady=4
    )

    ttk.Label(frm, text="Device name").grid(row=3, column=0, sticky="w")
    name_var = tk.StringVar(value=platform.node())
    ttk.Entry(frm, textvariable=name_var, width=42).grid(row=3, column=1, sticky="ew", pady=4)

    status_var = tk.StringVar(
        value="Defaults: desktop view/control + files_read (configure later on the manager)."
    )
    ttk.Label(frm, textvariable=status_var, wraplength=360).grid(
        row=4, column=0, columnspan=2, sticky="w", pady=(8, 4)
    )

    def submit() -> None:
        try:
            status_var.set("Signing in and enrolling...")
            root.update_idletasks()
            server_url = server_var.get()
            _, insecure = resolve_server_and_insecure(server_url)
            added = enroll_with_account(
                state,
                server=server_url,
                username=user_var.get().strip(),
                password=pass_var.get(),
                name=name_var.get().strip() or platform.node(),
                allow_insecure=insecure,
            )
            result["controller"] = added
            result["cancelled"] = False
            if on_success:
                on_success(added)
            messagebox.showinfo(
                "Done",
                "Device enrolled. Connection will stay running; name/share/permissions can be configured later.",
            )
            root.destroy()
        except (DeviceExecutionError, OSError, ValueError) as exc:
            status_var.set(str(exc))
            messagebox.showerror("Join failed", str(exc))

    def cancel() -> None:
        result["cancelled"] = True
        root.destroy()

    btns = ttk.Frame(frm)
    btns.grid(row=5, column=0, columnspan=2, sticky="e", pady=(12, 0))
    ttk.Button(btns, text="Cancel", command=cancel).grid(row=0, column=0, padx=4)
    ttk.Button(btns, text="Sign in and join", command=submit).grid(row=0, column=1, padx=4)

    root.protocol("WM_DELETE_WINDOW", cancel)
    root.mainloop()
    return None if result["cancelled"] else result["controller"]