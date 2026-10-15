"""Device-local browser pages; only bounded pixels, observations and input cross RPC."""

from __future__ import annotations

import asyncio
import base64
import importlib.util
import math
import os
import re
import shutil
import time
from contextlib import suppress
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import uuid4


def browser_runtime() -> dict[str, Any]:
    """Discover locally, without launching Chrome or installing dependencies."""
    dependency = importlib.util.find_spec("playwright") is not None
    candidates = [
        shutil.which(name)
        for name in ("chromium", "chromium-browser", "google-chrome", "chrome", "msedge")
    ]
    if os.name == "nt":
        for variable in ("PROGRAMFILES", "PROGRAMFILES(X86)", "LOCALAPPDATA"):
            if base := os.environ.get(variable):
                candidates.extend(
                    str(Path(base) / suffix)
                    for suffix in (
                        "Google/Chrome/Application/chrome.exe",
                        "Microsoft/Edge/Application/msedge.exe",
                    )
                )
    cache = Path(
        os.environ.get("PLAYWRIGHT_BROWSERS_PATH")
        or (
            str(Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "ms-playwright")
            if os.name == "nt"
            else str(Path.home() / ".cache/ms-playwright")
        )
    )
    bundled: list[str] = []
    for pattern in (
        "chromium-*/chrome-win*/chrome.exe",
        "chromium-*/chrome-linux*/chrome",
        "chromium-*/chrome-mac*/Chromium.app/Contents/MacOS/Chromium",
    ):
        bundled.extend(str(path) for path in sorted(cache.glob(pattern), reverse=True))
    # Prefer the browser paired with Playwright. Branded system installations
    # can override --user-data-dir through policy and reject automation even
    # with an explicit isolated profile (notably on Windows runner images).
    binary = next(
        (value for value in [*bundled, *candidates] if value and Path(value).is_file()), None
    )
    return {
        "dependency_available": dependency,
        "executable": binary,
        "available": dependency and binary is not None,
        "reason": None
        if dependency and binary
        else "playwright dependency unavailable"
        if not dependency
        else "Chromium/Chrome/Edge executable unavailable",
    }


def _url(value: Any) -> str:
    if value == "about:blank":
        return "about:blank"
    if not isinstance(value, str) or len(value) > 4096 or "\x00" in value:
        raise ValueError("invalid browser URL")
    parsed = urlsplit(value)
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username
        or parsed.password
    ):
        raise ValueError("browser URL must use http(s) without embedded credentials")
    return value


class DeviceBrowsers:
    def __init__(self, state_dir: Path) -> None:
        self.state_dir = state_dir
        self.playwright: Any = None
        self.context: Any = None
        self.sessions: dict[str, dict[str, Any]] = {}
        self.lock = asyncio.Lock()
        self._cleanup_task: asyncio.Task[None] | None = None

    async def _launch(self) -> None:
        if self.context is not None:
            return
        runtime = browser_runtime()
        if not runtime["available"]:
            raise ValueError(str(runtime["reason"]))
        from playwright.async_api import async_playwright

        if self.playwright is not None:
            await self.playwright.stop()
        self.playwright = await async_playwright().start()
        profile = self.state_dir / "profile"
        profile.mkdir(parents=True, exist_ok=True)
        if os.name == "posix":
            profile.chmod(0o700)
        try:
            self.context = await self.playwright.chromium.launch_persistent_context(
                str(profile),
                executable_path=runtime["executable"],
                headless=True,
                viewport={"width": 1280, "height": 800},
                accept_downloads=False,
            )
            for page in self.context.pages:
                await page.close()
            self.context.on("close", self._disconnected)
            if self._cleanup_task is None or self._cleanup_task.done():
                self._cleanup_task = asyncio.create_task(self._idle_cleanup())
        except BaseException:
            await self.playwright.stop()
            self.playwright = None
            raise

    async def _expire_idle(self) -> None:
        now = time.monotonic()
        for key, session in list(self.sessions.items()):
            if now - session["last_seen"] > 300:
                for page in list(session["pages"].values()):
                    with suppress(Exception):
                        await page.close()
                del self.sessions[key]
        if not self.sessions:
            await self._close_runtime()

    async def _idle_cleanup(self) -> None:
        while True:
            await asyncio.sleep(30)
            async with self.lock:
                await self._expire_idle()
                if self.context is None:
                    return

    def _disconnected(self) -> None:
        self.context = None
        self.sessions.clear()

    def _track(self, session: dict[str, Any], page: Any) -> str:
        identity = uuid4().hex
        session["pages"][identity] = page

        async def popup(child: Any) -> None:
            async with self.lock:
                if (
                    session not in self.sessions.values()
                    or sum(len(s["pages"]) for s in self.sessions.values()) >= 16
                ):
                    await child.close()
                    return
                session["active"] = self._track(session, child)

        page.on("popup", popup)
        return identity

    async def _state(self, session: dict[str, Any]) -> dict[str, Any]:
        session["pages"] = {
            key: page for key, page in session["pages"].items() if not page.is_closed()
        }
        if session["active"] not in session["pages"]:
            session["active"] = next(iter(session["pages"]), None)
        tabs = []
        for identity, page in session["pages"].items():
            title = ""
            with suppress(Exception):
                title = (await page.title())[:300]
            tabs.append(
                {
                    "id": identity,
                    "url": page.url,
                    "title": title,
                    "active": identity == session["active"],
                }
            )
        return {
            "session_id": session["id"],
            "origin_context_id": session["context_id"],
            "tabs": tabs,
            "width": 1280,
            "height": 800,
        }

    async def call(self, action: str, params: dict[str, Any]) -> dict[str, Any]:
        lane = params.get("browser_lane")
        if not isinstance(lane, str) or not re.fullmatch(r"[a-f0-9]{64}", lane):
            raise ValueError("authenticated browser lane required")
        async with self.lock:
            await self._expire_idle()
            now = time.monotonic()
            session = self.sessions.get(lane)
            if action == "browser.open":
                if session is None:
                    if len(self.sessions) >= 8:
                        raise ValueError("device browser session capacity reached")
                    await self._launch()
                    if sum(len(item["pages"]) for item in self.sessions.values()) >= 16:
                        raise ValueError("device browser tab capacity reached")
                    page = await self.context.new_page()
                    session = {
                        "id": uuid4().hex,
                        "context_id": params.get("execution_context_id"),
                        "pages": {},
                        "active": None,
                        "last_seen": now,
                    }
                    session["active"] = self._track(session, page)
                    self.sessions[lane] = session
                session["last_seen"] = now
                return await self._state(session)
            if session is None:
                raise ValueError("browser session unavailable; explicitly open a session")
            session["last_seen"] = now
            if action == "browser.close":
                for page in session["pages"].values():
                    await page.close()
                del self.sessions[lane]
                if not self.sessions:
                    await self._close_runtime()
                return {"closed": True, "session_id": session["id"]}
            if action == "browser.state":
                return await self._state(session)
            await self._state(session)
            if action == "browser.action" and params.get("command") == "new_tab":
                if sum(len(item["pages"]) for item in self.sessions.values()) >= 16:
                    raise ValueError("device browser tab capacity reached")
                url = _url(params.get("url") or "about:blank")
                page = await self.context.new_page()
                session["active"] = self._track(session, page)
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
                return await self._state(session)
            page = session["pages"].get(session["active"])
            if page is None or page.is_closed():
                raise ValueError("browser page closed; open a new tab")
            if action == "browser.capture":
                image = await page.screenshot(type="jpeg", quality=60, timeout=5000)
                if len(image) > 512 * 1024:
                    raise ValueError("browser frame exceeds 512 KiB budget")
                return {
                    **await self._state(session),
                    "data_b64": base64.b64encode(image).decode(),
                    "mime": "image/jpeg",
                    "url": page.url,
                }
            if action == "browser.observe":
                observation = await page.evaluate(
                    """() => Array.from(document.querySelectorAll('a,button,input,textarea,select,[role=button],[contenteditable=true]')).slice(0,200).map((e,i)=>{const ref='o'+i; e.setAttribute('data-octop-ref',ref); return {ref,tag:e.tagName,role:e.getAttribute('role'),text:(e.innerText||e.getAttribute('aria-label')||e.getAttribute('placeholder')||'').slice(0,160)};})"""
                )
                return {
                    "session_id": session["id"],
                    "url": page.url,
                    "title": (await page.title())[:300],
                    "elements": observation,
                    "text": (await page.locator("body").inner_text(timeout=5000))[:16000],
                    "bounded": True,
                }
            if action != "browser.action":
                raise ValueError("unsupported browser action")
            command = params.get("command")
            if command == "reset_input":
                for button in ("left", "right", "middle"):
                    await page.mouse.up(button=button)
                for key in ("Control", "Alt", "Shift", "Meta"):
                    await page.keyboard.up(key)
            elif command == "navigate":
                url = _url(params.get("url") or "about:blank")
                await page.goto(url, wait_until="domcontentloaded", timeout=15000)
            elif command in {"switch_tab", "close_tab"}:
                identity = str(params.get("tab_id") or session["active"])
                target = session["pages"].get(identity)
                if target is None:
                    raise ValueError("browser tab does not belong to this session")
                if command == "close_tab":
                    await target.close()
                else:
                    session["active"] = identity
            elif command in {"go_back", "go_forward", "reload"}:
                await getattr(page, command)(wait_until="domcontentloaded", timeout=15000)
            elif command in {"click", "dblclick", "hover", "type", "fill", "select"}:
                ref, selector = params.get("ref"), params.get("selector")
                if ref:
                    if not isinstance(ref, str) or not re.fullmatch(r"o[0-9]{1,3}", ref):
                        raise ValueError("unknown browser element ref")
                    selector = f'[data-octop-ref="{ref}"]'
                if selector:
                    if not isinstance(selector, str) or len(selector) > 2000:
                        raise ValueError("invalid browser selector")
                    locator = page.locator(selector)
                    if await locator.count() != 1:
                        raise ValueError(
                            "browser target must match exactly one element; observe again"
                        )
                    if command in {"type", "fill"}:
                        await locator.fill(self._text(params), timeout=5000)
                    elif command == "select":
                        await locator.select_option(self._text(params), timeout=5000)
                    else:
                        await getattr(locator, command)(timeout=5000)
                elif command in {"click", "dblclick", "hover"}:
                    x, y = self._coordinates(params)
                    await getattr(page.mouse, "move" if command == "hover" else command)(x, y)
                elif command == "type":
                    await page.keyboard.insert_text(self._text(params))
                else:
                    raise ValueError("browser selector or ref required")
            elif command == "press":
                press_key = params.get("key") or params.get("text")
                if not isinstance(press_key, str) or not press_key or len(press_key) > 100:
                    raise ValueError("invalid browser key")
                await page.keyboard.press(press_key)
            elif command == "scroll":
                amount = self._number(params.get("amount", 300), 5000)
                dx = self._number(params.get("deltaX", 0), 5000)
                dy = self._number(
                    params.get("deltaY", -amount if params.get("direction") == "up" else amount),
                    5000,
                )
                if "x" in params:
                    await page.mouse.move(*self._coordinates(params))
                await page.mouse.wheel(dx, dy)
            elif command in {"mousedown", "mousemove", "mouseup"}:
                x, y = self._coordinates(params)
                button = params.get("button", "left")
                if button not in {"left", "right", "middle", "none"}:
                    raise ValueError("invalid browser pointer button")
                count = params.get("clickCount", 1)
                if type(count) is not int or not 1 <= count <= 3:
                    raise ValueError("invalid browser click count")
                await page.mouse.move(x, y)
                if command != "mousemove":
                    if button == "none":
                        raise ValueError("pressed browser button required")
                    await getattr(page.mouse, "down" if command == "mousedown" else "up")(
                        button=button, click_count=count
                    )
            elif command == "eval_js":
                expression = params.get("expression")
                if not isinstance(expression, str) or len(expression) > 16000:
                    raise ValueError("invalid browser expression")
                value = await page.evaluate(expression)
                return {"session_id": session["id"], "value": str(value)[:16000], "bounded": True}
            else:
                raise ValueError("unsupported browser input")
            return await self._state(session)

    @staticmethod
    def _text(params: dict[str, Any]) -> str:
        text = params.get("text") or ""
        if not isinstance(text, str) or len(text) > 16000:
            raise ValueError("browser text exceeds input budget")
        return text

    @staticmethod
    def _coordinates(params: dict[str, Any]) -> tuple[float, float]:
        x, y = params.get("x"), params.get("y")
        if (
            not isinstance(x, (int, float))
            or not isinstance(y, (int, float))
            or not 0 <= x < 1280
            or not 0 <= y < 800
        ):
            raise ValueError("browser coordinates outside viewport")
        return x, y

    @staticmethod
    def _number(value: Any, limit: int) -> float:
        if (
            type(value) not in {int, float}
            or not math.isfinite(value)
            or not -limit <= value <= limit
        ):
            raise ValueError("invalid browser scroll")
        return float(value)

    async def _close_runtime(self) -> None:
        try:
            if self.context is not None:
                await self.context.close()
        finally:
            self.context = None
            if self.playwright is not None:
                await self.playwright.stop()
                self.playwright = None
            self.sessions.clear()

    async def close_all(self) -> None:
        if self._cleanup_task is not None:
            self._cleanup_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._cleanup_task
            self._cleanup_task = None
        async with self.lock:
            await self._close_runtime()
