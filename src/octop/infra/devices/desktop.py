"""Bounded desktop operations on one native thread, independent of WS heartbeats."""

from __future__ import annotations

import asyncio
import contextlib
import math
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any, cast

from octop.infra.desktop.capture import ScreenCapture
from octop.infra.desktop.input import InputInjector

_KEYS = {
    value.lower(): value
    for value in (
        "Enter",
        "Backspace",
        "Tab",
        "Escape",
        "Delete",
        "ArrowUp",
        "ArrowDown",
        "ArrowLeft",
        "ArrowRight",
        "Home",
        "End",
        "PageUp",
        "PageDown",
        "Control",
        "Shift",
        "Alt",
        "Meta",
        *(f"F{i}" for i in range(1, 13)),
    )
}
_KEYS.update(
    {
        "esc": "Escape",
        "ctrl": "Control",
        "cmd": "Meta",
        "win": "Meta",
        "up": "ArrowUp",
        "down": "ArrowDown",
        "left": "ArrowLeft",
        "right": "ArrowRight",
    }
)
_MODIFIERS = {"Control", "Shift", "Alt", "Meta"}


def _chord(value: Any) -> list[str]:
    if not isinstance(value, str) or not value or len(value) > 100:
        raise ValueError("invalid input key")
    parts = value.split("+") if len(value) > 1 else [value]
    keys = [_KEYS.get(part.lower(), part) for part in parts]
    if (
        len(keys) > 5
        or len(set(keys)) != len(keys)
        or any(len(key) != 1 and key not in _KEYS.values() for key in keys)
        or any(key not in _MODIFIERS for key in keys[:-1])
        or any(ord(key) < 32 for key in keys if len(key) == 1)
    ):
        raise ValueError("invalid input key")
    return keys


def _point(params: dict[str, Any]) -> tuple[int, int]:
    values = (params.get("x"), params.get("y"))
    if any(type(value) is not int or abs(value) > 1_000_000 for value in values):
        raise ValueError("invalid desktop coordinates")
    return cast(int, values[0]), cast(int, values[1])


class DeviceDesktop:
    def __init__(self) -> None:
        # mss stores native handles in thread-local state. Creation, capture and
        # disposal must all run on this same thread, never the connection loop.
        self._pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="octop-desktop")
        self._capture: ScreenCapture | None = None
        self._injector: InputInjector | None = None
        self._pending = 0
        self._closed = False

    async def call(
        self,
        action: str,
        params: dict[str, Any],
        guard: Callable[[], contextlib.AbstractContextManager[Any]],
    ) -> dict[str, Any]:
        if self._closed or self._pending >= 4:
            raise ValueError("desktop worker unavailable or busy")
        self._pending += 1
        try:
            return await asyncio.get_running_loop().run_in_executor(
                self._pool, self._run, action, params, guard
            )
        finally:
            self._pending -= 1

    def _run(
        self,
        action: str,
        params: dict[str, Any],
        guard: Callable[[], contextlib.AbstractContextManager[Any]],
    ) -> dict[str, Any]:
        if action == "desktop.capture":
            quality = params.get("quality", 80)
            if type(quality) is not int or not 1 <= quality <= 100:
                raise ValueError("invalid quality")
            with guard():
                pass
            if self._capture is None:
                self._capture = ScreenCapture()
            frame = self._capture.capture_jpeg(quality=quality)
            if frame is None:
                raise ValueError(
                    "desktop capture unavailable: no accessible display or capture backend"
                )
            with guard():
                # A slow capture must not disclose a frame after access is revoked.
                if len(frame.jpeg_b64) > 2 * 1024 * 1024:
                    raise ValueError("desktop frame too large; reduce quality")
                return {
                    "jpeg_b64": frame.jpeg_b64,
                    "width": frame.width,
                    "height": frame.height,
                    "left": getattr(frame, "left", 0),
                    "top": getattr(frame, "top", 0),
                }
        if action != "desktop.input":
            raise ValueError("unsupported desktop action")
        with guard():
            if self._injector is None:
                self._injector = InputInjector()
            self._input(params, self._injector)
        return {"ok": True}

    @staticmethod
    def _input(params: dict[str, Any], injector: InputInjector) -> None:
        kind = params.get("kind")
        if kind in {"click", "move", "scroll"}:
            x, y = _point(params)
            if kind == "click":
                button = params.get("button", "left")
                if button not in {"left", "right", "middle"}:
                    raise ValueError("invalid mouse button")
                injector.click(x, y, button=button)
            elif kind == "move":
                injector.mouse_move(x, y)
            else:
                dx, dy = params.get("dx", 0), params.get("dy", 0)
                if any(
                    type(n) not in {int, float} or not math.isfinite(n) or abs(n) > 10000
                    for n in (dx, dy)
                ):
                    raise ValueError("invalid scroll delta")
                injector.scroll(x, y, delta_x=dx, delta_y=dy)
        elif kind == "type":
            text = params.get("text")
            if not isinstance(text, str) or len(text) > 10000 or "\x00" in text:
                raise ValueError("invalid input text")
            injector.type_text(text)
        elif kind == "key":
            keys = _chord(params.get("key"))
            with contextlib.ExitStack() as releases:
                for key in keys:
                    releases.callback(injector.key_up, key)
                    injector.key_down(key)
        else:
            raise ValueError("unsupported input kind")

    async def close(self) -> None:
        if self._closed:
            return
        self._closed = True

        def dispose() -> None:
            if self._capture is not None:
                self._capture.close()
                self._capture = None
            self._injector = None

        try:
            await asyncio.get_running_loop().run_in_executor(self._pool, dispose)
        finally:
            self._pool.shutdown(wait=False, cancel_futures=True)
