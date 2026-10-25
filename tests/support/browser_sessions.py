"""Mint durable browser JWTs (sid + auth_version) for unit tests."""

from __future__ import annotations

import secrets
import time
from typing import Any


def mint_browser_token(
    *,
    secret: bytes,
    repos: Any,
    user_id: int,
    username: str,
    role: str,
    ttl_seconds: int = 3600,
) -> str:
    """Create a ``browser_sessions`` row and sign a JWT carrying ``sid`` + ``av``."""
    from octop.infra.auth.tokens import sign_token

    row = repos.user_repo.get(int(user_id))
    if row is None:
        raise RuntimeError(f"user {user_id} missing")
    av = int(getattr(row, "auth_version", 1) or 1)
    sid = secrets.token_urlsafe(16)
    repos.browser_session_repo.create(
        sid=sid,
        user_id=int(user_id),
        absolute_expires_at=time.time() + max(1, int(ttl_seconds)),
        auth_version_at_issue=av,
    )
    return sign_token(
        secret,
        sub=int(user_id),
        uname=str(username),
        role=str(role),
        ttl_seconds=int(ttl_seconds),
        sid=sid,
        av=av,
    )
