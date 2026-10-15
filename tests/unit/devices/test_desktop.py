"""Desktop transport uses native-thread I/O and truthful, non-replayed input receipts."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from octop.infra.devices.executor import DeviceExecutionError, DeviceExecutor


@pytest.fixture
def desktop(tmp_path, monkeypatch):
    permissions = ["desktop_view", "desktop_control"]
    monkeypatch.setattr(DeviceExecutor, "capabilities", property(lambda self: permissions))
    executor = DeviceExecutor(permissions, [], state_dir=tmp_path, trust_mode="owner")
    executor.update_grants(1, permissions, [])
    return executor


async def call(executor, action, params, operation_id="test"):
    return await executor.execute(
        operation_id,
        action,
        params,
        grant_version=executor.grant_version,
        permissions=list(executor.permissions),
    )


@pytest.mark.parametrize(
    "key,keys",
    [
        ("enter", ["Enter"]),
        ("esc", ["Escape"]),
        ("up", ["ArrowUp"]),
        ("ctrl+c", ["Control", "c"]),
        ("Control+Shift+Tab", ["Control", "Shift", "Tab"]),
        ("+", ["+"]),
    ],
)
async def test_ui_keys_and_chords_release_all_modifiers(desktop, monkeypatch, key, keys):
    injector = MagicMock()
    monkeypatch.setattr("octop.infra.devices.desktop.InputInjector", lambda: injector)
    try:
        assert await call(desktop, "desktop.input", {"kind": "key", "key": key}) == {"ok": True}
        assert [c.args[0] for c in injector.key_down.call_args_list] == keys
        assert [c.args[0] for c in injector.key_up.call_args_list] == keys[::-1]
        # Retrying the same operation after reconnect cannot type twice.
        await call(desktop, "desktop.input", {"kind": "key", "key": key})
        assert injector.key_down.call_count == len(keys)
    finally:
        await desktop.close()


async def test_failed_key_press_releases_modifiers_and_is_not_success(desktop, monkeypatch):
    injector = MagicMock()
    injector.key_down.side_effect = [None, OSError("OS denied input")]
    monkeypatch.setattr("octop.infra.devices.desktop.InputInjector", lambda: injector)
    try:
        with pytest.raises(DeviceExecutionError):
            await call(desktop, "desktop.input", {"kind": "key", "key": "ctrl+c"})
        assert [c.args[0] for c in injector.key_up.call_args_list] == ["c", "Control"]
        assert desktop.reconciliation_results()[0]["ok"] is False
    finally:
        await desktop.close()


async def test_native_negative_coordinates_and_scroll_direction(desktop, monkeypatch):
    injector = MagicMock()
    monkeypatch.setattr("octop.infra.devices.desktop.InputInjector", lambda: injector)
    try:
        await call(desktop, "desktop.input", {"kind": "scroll", "x": -100, "y": -50, "dy": -120})
        injector.scroll.assert_called_once_with(-100, -50, delta_x=0, delta_y=-120)
        with pytest.raises(DeviceExecutionError, match="coordinates"):
            await call(desktop, "desktop.input", {"kind": "scroll", "dy": 120}, "invalid")
        with pytest.raises(DeviceExecutionError, match="scroll delta"):
            await call(
                desktop,
                "desktop.input",
                {"kind": "scroll", "x": 0, "y": 0, "dy": float("inf")},
                "infinite",
            )
    finally:
        await desktop.close()


async def test_capture_does_not_block_connection_loop_and_closes_on_same_thread(
    desktop, monkeypatch
):
    started, release = threading.Event(), threading.Event()
    threads = []

    class Capture:
        def __init__(self):
            threads.append(threading.get_ident())

        def capture_jpeg(self, **kwargs):
            threads.append(threading.get_ident())
            started.set()
            assert release.wait(3)
            return SimpleNamespace(
                jpeg_b64="private-frame", width=100, height=80, left=-100, top=-80
            )

        def close(self):
            threads.append(threading.get_ident())

    monkeypatch.setattr("octop.infra.devices.desktop.ScreenCapture", Capture)
    task = asyncio.create_task(call(desktop, "desktop.capture", {}))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        # Capture is still waiting while connection-loop work can complete.
        assert not release.is_set()
        result = await asyncio.wait_for(call(desktop, "ping", {}, "heartbeat"), 0.5)
        assert result["hostname"]
        release.set()
        frame = await task
        assert (frame["left"], frame["top"]) == (-100, -80)
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await desktop.close()
    assert len(set(threads)) == 1
    assert threads[0] != threading.get_ident()


async def test_cancelled_queued_input_never_reaches_os(desktop, monkeypatch):
    started, release = threading.Event(), threading.Event()
    injector = MagicMock()

    def capture(self, **kwargs):
        started.set()
        assert release.wait(3)
        return SimpleNamespace(jpeg_b64="frame", width=10, height=10)

    monkeypatch.setattr("octop.infra.desktop.capture.ScreenCapture.capture_jpeg", capture)
    monkeypatch.setattr("octop.infra.devices.desktop.InputInjector", lambda: injector)
    capture_task = asyncio.create_task(call(desktop, "desktop.capture", {}, "capture"))
    input_task = None
    try:
        assert await asyncio.to_thread(started.wait, 1)
        input_task = asyncio.create_task(
            call(desktop, "desktop.input", {"kind": "type", "text": "private"}, "input")
        )
        await asyncio.sleep(0.02)
        input_task.cancel()
        await asyncio.sleep(0)
        release.set()
        await capture_task
        with pytest.raises(asyncio.CancelledError):
            await input_task
        injector.type_text.assert_not_called()
    finally:
        release.set()
        await asyncio.gather(
            capture_task, *([input_task] if input_task else []), return_exceptions=True
        )
        await desktop.close()


async def test_revoked_access_during_capture_cannot_deliver_private_frame(desktop, monkeypatch):
    started, release = threading.Event(), threading.Event()

    def capture(self, **kwargs):
        started.set()
        assert release.wait(3)
        return SimpleNamespace(jpeg_b64="private-frame", width=10, height=10)

    monkeypatch.setattr("octop.infra.desktop.capture.ScreenCapture.capture_jpeg", capture)
    task = asyncio.create_task(call(desktop, "desktop.capture", {}))
    try:
        assert await asyncio.to_thread(started.wait, 1)
        desktop.update_grants(2, [], [])
        release.set()
        with pytest.raises(DeviceExecutionError, match="stale device grant"):
            await task
    finally:
        release.set()
        await asyncio.gather(task, return_exceptions=True)
        await desktop.close()
