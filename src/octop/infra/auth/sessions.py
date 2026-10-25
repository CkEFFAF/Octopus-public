"""Browser JWT session lifecycle (F06): sid + auth_version, durable revoke."""

from __future__ import annotations

import secrets
import time
from typing import TYPE_CHECKING, Any

from octop.infra.auth.tokens import sign_token
from octop.infra.errors import ErrorCode, OctopError

if TYPE_CHECKING:
    from octop.infra.server import OctopServer
    from octop.infra.users.identity import User


def _new_sid() -> str:
    return secrets.token_urlsafe(32)


def current_auth_version(server: OctopServer, user_id: int) -> int:
    assert server.services is not None
    row = server.services.user_repo.get(int(user_id))
    if row is None:
        raise OctopError(ErrorCode.USER_DISABLED, "user not active")
    return int(getattr(row, "auth_version", 1) or 1)


def issue_browser_access_token(
    server: OctopServer,
    user: User,
    *,
    ttl_seconds: int | None = None,
) -> str:
    """Create a durable browser session and sign a JWT with sid + av."""
    assert server.services is not None
    secret = server.services.secret_repo.get("jwt")
    if secret is None:
        raise OctopError(ErrorCode.INTERNAL_ERROR, "jwt secret missing")
    ttl = int(
        ttl_seconds
        if ttl_seconds is not None
        else server.services.config.access_token_ttl_seconds
    )
    ttl = max(1, ttl)
    av = current_auth_version(server, int(user.id))
    now = time.time()
    sid = _new_sid()
    server.services.repos.browser_session_repo.create(
        sid=sid,
        user_id=int(user.id),
        absolute_expires_at=now + ttl,
        auth_version_at_issue=av,
        created_at=now,
    )
    return sign_token(
        secret,
        sub=int(user.id),
        uname=str(user.username),
        role=str(user.role),
        ttl_seconds=ttl,
        sid=sid,
        av=av,
    )


def validate_browser_session(
    server: OctopServer,
    *,
    user_id: int,
    sid: str,
    av: int,
) -> None:
    """Raise if the browser session is missing, revoked, expired, or av-mismatched."""
    assert server.services is not None
    row = server.services.user_repo.get(int(user_id))
    if row is None or int(row.disabled):
        raise OctopError(ErrorCode.USER_DISABLED, "user not active")
    current_av = int(getattr(row, "auth_version", 1) or 1)
    if int(av) != current_av:
        raise OctopError(ErrorCode.AUTH_FAILED, "session revoked")
    session = server.services.repos.browser_session_repo.get(str(sid))
    if session is None or int(session["user_id"]) != int(user_id):
        raise OctopError(ErrorCode.AUTH_FAILED, "invalid session")
    if session.get("revoked_at") is not None:
        raise OctopError(ErrorCode.AUTH_FAILED, "session revoked")
    if float(session["absolute_expires_at"]) <= time.time():
        raise OctopError(ErrorCode.AUTH_FAILED, "session expired")
    if int(session["auth_version_at_issue"]) != current_av:
        raise OctopError(ErrorCode.AUTH_FAILED, "session revoked")


def revoke_browser_session(server: OctopServer, sid: str) -> None:
    assert server.services is not None
    server.services.repos.browser_session_repo.revoke(str(sid))


def bump_auth_version_and_revoke_browser_sessions(services: Any, user_id: int) -> int:
    """Atomically bump users.auth_version and revoke all browser sessions for the user.

    ``services`` is SharedServices (or any object with ``.db``).
    """
    uid = int(user_id)
    now = time.time()
    with services.db.transaction() as conn:
        conn.execute(
            "UPDATE users SET auth_version = auth_version + 1 WHERE id = ?",
            (uid,),
        )
        row = conn.execute(
            "SELECT auth_version FROM users WHERE id = ?",
            (uid,),
        ).fetchone()
        if row is None:
            raise OctopError(ErrorCode.NOT_FOUND, "user not found")
        av = int(row["auth_version"] if hasattr(row, "keys") else row[0])
        conn.execute(
            "UPDATE browser_sessions SET revoked_at = COALESCE(revoked_at, ?) "
            "WHERE user_id = ? AND revoked_at IS NULL",
            (now, uid),
        )
    return av


def browser_claims_from_payload(payload: dict[str, Any]) -> tuple[str, int] | None:
    """Return (sid, av) when payload is a browser JWT; None for access-key JWTs."""
    if payload.get("auth_key_id") is not None:
        return None
    sid = payload.get("sid")
    av = payload.get("av")
    if not isinstance(sid, str) or not sid:
        return None
    if av is None:
        return None
    try:
        return sid, int(av)
    except (TypeError, ValueError):
        return None
