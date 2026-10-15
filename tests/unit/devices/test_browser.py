"""Real device Chromium: local HTTP/WebSocket, input and transport reattachment."""

from __future__ import annotations

import base64
import hashlib
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

import pytest
from websockets.asyncio.server import serve

from octop.infra.devices import browser
from octop.infra.devices.executor import DeviceExecutor


async def test_native_browser_localhost_websocket_input_and_reattachment(tmp_path: Path) -> None:
    if not browser.browser_runtime()["available"]:
        pytest.skip("native Chromium and Playwright are required")

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(b"""<!doctype html><title>Device local preview</title>
            <input id='name' aria-label='Name'><button id='save' onclick="document.querySelector('#result').textContent=document.querySelector('#name').value">Save</button>
            <p id='result'>Waiting</p><div style='height:2000px'>Local page</div>""")

        def log_message(self, *_args: Any) -> None:
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    serving = threading.Thread(target=server.serve_forever, daemon=True)
    serving.start()
    executor = DeviceExecutor(
        ["command_exec"],
        [],
        trust_mode="owner",
        working_dir=str(tmp_path),
        state_dir=tmp_path / "state",
    )
    lane = hashlib.sha256(b"authenticated-owner-expert-thread").hexdigest()
    params = {"browser_lane": lane, "execution_context_id": "run-one"}

    async def call(action: str, **values: Any) -> dict[str, Any]:
        return await executor.execute(
            "ephemeral",
            "browser." + action,
            {**params, **values},
            grant_version=0,
            permissions=["command_exec"],
        )

    async def echo(socket: Any) -> None:
        await socket.send("DEVICE_WS=" + await socket.recv())

    try:
        opened = await call("open")
        original_tab = opened["tabs"][0]["id"]
        url = f"http://127.0.0.1:{server.server_port}/"
        state = await call("action", command="navigate", url=url)
        assert state["tabs"][0]["title"] == "Device local preview"
        dom = await call("observe")
        input_ref = next(item["ref"] for item in dom["elements"] if item["tag"] == "INPUT")
        await call("action", command="type", ref=input_ref, text="设备输入")
        position = await call(
            "action",
            command="eval_js",
            expression="JSON.stringify(document.querySelector('#save').getBoundingClientRect().toJSON())",
        )
        import json

        rect = json.loads(position["value"])
        for command in ("mousedown", "mousemove", "mouseup"):
            await call("action", command=command, x=rect["x"] + 5, y=rect["y"] + 5, button="left")
        assert "设备输入" in (await call("observe"))["text"]
        frame = await call("capture")
        image = base64.b64decode(frame["data_b64"])
        assert image.startswith(b"\xff\xd8") and len(image) <= 512 * 1024
        assert frame["tabs"][0]["url"] == url
        async with serve(echo, "127.0.0.1", 0) as websocket:
            port = websocket.sockets[0].getsockname()[1]
            result = await call(
                "action",
                command="eval_js",
                expression=f"new Promise((resolve,reject)=>{{let w=new WebSocket('ws://127.0.0.1:{port}');w.onopen=()=>w.send('live');w.onmessage=e=>{{resolve(e.data);w.close()}};w.onerror=reject;}})",
            )
            assert result["value"] == "DEVICE_WS=live"
        await executor.close(preserve_terminals=True)
        params["execution_context_id"] = "run-two"
        resumed = await call("open")
        assert resumed["session_id"] == opened["session_id"]
        assert resumed["tabs"][0]["id"] == original_tab
        assert "设备输入" in (await call("observe"))["text"]
        other = {
            "browser_lane": hashlib.sha256(b"other-thread").hexdigest(),
            "execution_context_id": "other-run",
        }
        await executor.execute(
            "other", "browser.open", other, grant_version=0, permissions=["command_exec"]
        )
        with pytest.raises(ValueError, match="does not belong"):
            await executor._browsers.call(
                "browser.action", {**other, "command": "switch_tab", "tab_id": original_tab}
            )
        await call("action", command="close_tab", tab_id=original_tab)
        assert (await call("state"))["tabs"] == []
        assert len((await call("action", command="new_tab"))["tabs"]) == 1
        # Frames, URL input and credentials are not saved in the replay journal.
        assert "ephemeral" not in executor._journal
        manager = executor._browsers
        for session in manager.sessions.values():
            session["last_seen"] -= 301
        async with manager.lock:
            await manager._expire_idle()
        assert manager.context is None and manager.playwright is None
        assert manager.sessions == {}
    finally:
        await executor.close()
        server.shutdown()
        server.server_close()
        serving.join(timeout=3)


async def test_browser_missing_runtime_is_an_explicit_device_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        browser,
        "browser_runtime",
        lambda: {"available": False, "reason": "Chromium executable unavailable"},
    )
    manager = browser.DeviceBrowsers(tmp_path)
    with pytest.raises(ValueError, match="Chromium executable unavailable"):
        await manager.call("browser.open", {"browser_lane": "a" * 64})
    assert manager.context is None and manager.sessions == {}


@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "javascript:alert(1)",
        "https://user:password@example.org/",
        "ftp://example.org/",
    ],
)
def test_browser_url_protocol_and_embedded_auth_are_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        browser._url(url)
