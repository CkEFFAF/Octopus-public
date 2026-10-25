"""Unit tests for F06 browser session + auth_version helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from octop.infra.auth.sessions import (
    browser_claims_from_payload,
    bump_auth_version_and_revoke_browser_sessions,
)
from octop.infra.auth.tokens import decode_token, sign_token
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.repos.browser_sessions import BrowserSessionRepo
from octop.infra.db.repos.users import UserRepo


def test_sign_token_includes_sid_and_av() -> None:
    token = sign_token(b"secret", sub=1, uname="a", role="user", sid="abc", av=3)
    payload = decode_token(b"secret", token)
    assert payload["sid"] == "abc"
    assert payload["av"] == 3


def test_browser_claims_from_payload() -> None:
    assert browser_claims_from_payload({"sid": "x", "av": 2}) == ("x", 2)
    assert browser_claims_from_payload({"auth_key_id": "k", "sid": "x", "av": 1}) is None
    assert browser_claims_from_payload({"av": 1}) is None
    assert browser_claims_from_payload({"sid": "x"}) is None


def test_bump_auth_version_revokes_sessions(tmp_path: Path) -> None:
    db = SqlitePool(tmp_path / "t.db")
    run_migrations(db)
    users = UserRepo(db)
    uid = users.create(username="u1", password_hash="x", role="user")
    sessions = BrowserSessionRepo(db)
    sessions.create(
        sid="s1",
        user_id=uid,
        absolute_expires_at=9e12,
        auth_version_at_issue=1,
    )
    services = SimpleNamespace(db=db)
    av = bump_auth_version_and_revoke_browser_sessions(services, uid)
    assert av == 2
    row = users.get(uid)
    assert row is not None and row.auth_version == 2
    sess = sessions.get("s1")
    assert sess is not None and sess["revoked_at"] is not None
