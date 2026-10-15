"""Desktop helpers; native device I/O does not load host installation services."""

from __future__ import annotations

from importlib import import_module
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from octop.infra.desktop.setup import DesktopStatus, desktop_status, desktop_supported

__all__ = ["DesktopStatus", "desktop_status", "desktop_supported"]


def __getattr__(name: str) -> Any:
    if name not in __all__:
        raise AttributeError(name)
    value = getattr(import_module("octop.infra.desktop.setup"), name)
    globals()[name] = value
    return value
