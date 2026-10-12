"""Apply Codex OAuth credentials to the Octop provider store."""

from __future__ import annotations

import json
import shutil
from typing import Any

from octop.infra.agents.providers.codex_oauth import (
    CODEX_BASE_URL,
    CodexOAuthCredentials,
    build_codex_headers,
    oauth_token_file,
    save_codex_token,
)
from octop.infra.utils.paths import PathLayout

CODEX_PROVIDER_NAME = "openai-codex"

CODEX_MODELS = [
    {"id": "gpt-5.4", "name": "GPT-5.4", "enabled": True, "input": ["text"]},
    {"id": "gpt-5.4-mini", "name": "GPT-5.4 mini", "enabled": True, "input": ["text"]},
    {"id": "gpt-5.5", "name": "GPT-5.5", "enabled": True, "input": ["text"]},
]


def codex_user_paths(services: Any, user_id: int) -> PathLayout:
    """Token files follow account ownership, never the hub's global OAuth session."""
    paths = PathLayout(services.paths.root / "users" / str(user_id))
    legacy_owner = services.settings_repo.get("providers.legacy_owner")
    legacy = oauth_token_file(services.paths)
    target = oauth_token_file(paths)
    if legacy_owner == str(user_id) and legacy.exists() and not target.exists():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(legacy), str(target))
    return paths


def apply_codex_credentials(
    services: Any,
    paths: PathLayout,
    cred: CodexOAuthCredentials,
    *,
    user_id: int,
    set_active: bool = True,
) -> int:
    """Create or update the ``openai-codex`` provider row. Returns provider id."""
    save_codex_token(paths, cred)
    account_id = cred.get("account_id", "")
    extra_json = json.dumps({"headers": build_codex_headers(account_id)})
    models_json = json.dumps(CODEX_MODELS)
    row = services.provider_repo.get_by_name(user_id, CODEX_PROVIDER_NAME)
    if row is None:
        pid = services.provider_repo.create(
            user_id=user_id,
            name=CODEX_PROVIDER_NAME,
            kind="openai",
            base_url=CODEX_BASE_URL,
            api_key=cred["access"],
            extra_json=extra_json,
            models_json=models_json,
            note="ChatGPT OAuth (Codex)",
        )
    else:
        services.provider_repo.update(
            user_id,
            row.id,
            kind="openai",
            base_url=CODEX_BASE_URL,
            api_key=cred["access"],
            extra_json=extra_json,
            models_json=models_json,
            enabled=True,
        )
        pid = row.id
    if set_active:
        services.settings_repo.set_active_model(user_id, CODEX_PROVIDER_NAME, "gpt-5.4")
    return int(pid)


def sync_refreshed_codex_api_key(
    services: Any, paths: PathLayout, access_token: str, *, user_id: int
) -> None:
    row = services.provider_repo.get_by_name(user_id, CODEX_PROVIDER_NAME)
    if row is not None:
        services.provider_repo.update(user_id, row.id, api_key=access_token)
