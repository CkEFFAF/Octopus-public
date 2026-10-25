"""Recheck access-key and browser JWT sockets at each message and while idle.

Long-lived WebSocket review (0038 Batch2 F07):
- Covered by this middleware (query token and/or start-frame token):
  desktop/stream, mobile/stream, browser/stream, terminal, mobile/shell,
  chat/ws, chat/notify_ws, bridge peer sockets that present JWT.
- Endpoint-level recheck before input: desktop/stream, mobile/stream.
- Access-key track remains separate from browser sid (DEC-0038-17).
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from typing import Any
from urllib.parse import parse_qs

from octop.infra.auth.sessions import browser_claims_from_payload, validate_browser_session
from octop.infra.auth.tokens import InvalidToken, decode_token
from octop.infra.errors import ErrorCode, OctopError


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
        browser_sid = payload.get("sid") if key_id is None else None
        closed = False

        async def valid() -> bool:
            nonlocal closed
            if closed:
                return False
            if key_id is not None:
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
            if browser_sid is not None:
                try:
                    claims = browser_claims_from_payload(payload)
                    if claims is None:
                        raise OctopError(ErrorCode.AUTH_FAILED, "session required")
                    sid, av = claims
                    validate_browser_session(
                        self.server, user_id=int(payload["sub"]), sid=sid, av=av
                    )
                except OctopError as exc:
                    closed = True
                    reason = "account disabled or session revoked"
                    if getattr(exc, "code", None) == ErrorCode.USER_DISABLED:
                        reason = "account disabled"
                    await send(
                        {
                            "type": "websocket.close",
                            "code": 4001,
                            "reason": reason,
                        }
                    )
                    return False
                return True
            return True

        async def checked_receive() -> Any:
            nonlocal payload, key_id, browser_sid
            tracked = key_id is not None or browser_sid is not None
            while await valid():
                try:
                    message = (
                        await receive()
                        if not tracked
                        else await asyncio.wait_for(receive(), timeout=1)
                    )
                except TimeoutError:
                    continue
                # Desktop/mobile streams authenticate in their first start frame.
                if (
                    key_id is None
                    and browser_sid is None
                    and message["type"] == "websocket.receive"
                ):
                    with contextlib.suppress(ValueError, TypeError):
                        frame = json.loads(message.get("text") or "")
                        if isinstance(frame, dict) and isinstance(frame.get("token"), str):
                            candidate = origin(frame["token"])
                            if candidate.get("auth_key_id") is not None:
                                payload, key_id = candidate, candidate["auth_key_id"]
                                tracked = True
                                if not await valid():
                                    break
                            elif candidate.get("sid"):
                                payload = candidate
                                browser_sid = candidate["sid"]
                                tracked = True
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
