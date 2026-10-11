"""Recheck key-origin browser sockets at each message and while idle."""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any
from urllib.parse import parse_qs

from octop.infra.auth.tokens import InvalidToken, decode_token
from octop.infra.errors import OctopError


class AccessKeyWebSocketMiddleware:
    def __init__(self, app: Any, server: Any) -> None:
        self.app = app
        self.server = server

    async def __call__(self, scope: Any, receive: Any, send: Any) -> None:
        if scope["type"] != "websocket":
            await self.app(scope, receive, send)
            return
        token = parse_qs(scope.get("query_string", b"").decode()).get("token", [""])[0]

        def origin(raw: str) -> dict[str, Any]:
            if self.server.services is not None:
                # The endpoint handles its usual authentication failures.
                with contextlib.suppress(InvalidToken, TypeError):
                    return decode_token(self.server.services.secret_repo.get("jwt"), raw)
            return {}

        payload = origin(token)
        key_id = payload.get("auth_key_id")
        closed = False

        async def valid() -> bool:
            nonlocal closed
            if closed:
                return False
            if key_id is None:
                return True
            try:
                self.server.app_runtime.devices.access_keys.validate_session(
                    int(payload["sub"]), str(key_id)
                )
            except OctopError:
                closed = True
                await send(
                    {
                        "type": "websocket.close",
                        "code": 4001,
                        "reason": "access key expired or revoked",
                    }
                )
                return False
            return True

        async def checked_receive() -> Any:
            nonlocal payload, key_id
            while await valid():
                try:
                    message = (
                        await receive()
                        if key_id is None
                        else await asyncio.wait_for(receive(), timeout=1)
                    )
                except TimeoutError:
                    continue
                # Desktop/mobile streams authenticate in their first start frame.
                if key_id is None and message["type"] == "websocket.receive":
                    with contextlib.suppress(ValueError, TypeError):
                        frame = json.loads(message.get("text") or "")
                        if isinstance(frame, dict) and isinstance(frame.get("token"), str):
                            candidate = origin(frame["token"])
                            if candidate.get("auth_key_id") is not None:
                                payload, key_id = candidate, candidate["auth_key_id"]
                                if not await valid():
                                    break
                return message
            return {"type": "websocket.disconnect", "code": 4001}

        async def checked_send(message: Any) -> None:
            if message["type"] == "websocket.close":
                if not closed:
                    await send(message)
            elif await valid():
                await send(message)

        await self.app(scope, checked_receive, checked_send)
