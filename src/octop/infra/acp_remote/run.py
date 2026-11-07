"""Entrypoint helpers for ``octop acp-remote``."""

from __future__ import annotations

import logging
from pathlib import Path

from octop.infra.acp_remote.agent import RemoteAcpAgent
from octop.infra.acp_remote.cloud import CloudClient
from octop.infra.acp_remote.sessions import SessionStore


def _read_token(token_file: Path | None, token: str | None) -> str:
    if token_file is not None:
        raw = token_file.read_text(encoding="utf-8").strip()
        if not raw:
            raise ValueError("token file is empty")
        return raw
    if token:
        return token.strip()
    raise ValueError("token required via --token-file or OCTOP_ACP_TOKEN")


async def run_acp_remote(
    *,
    server: str,
    expert: str,
    token_file: Path | None = None,
    token: str | None = None,
    sessions_path: Path | None = None,
    debug: bool = False,
) -> None:
    import sys

    from acp import run_agent

    level = logging.DEBUG if debug else logging.WARNING
    logging.basicConfig(level=level, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s")

    secret = _read_token(token_file, token)
    # Derive a stable credential id label without logging the secret.
    credential_id = "oaa"
    if secret.startswith("oaa_") and len(secret) > 12:
        credential_id = f"oaa_{secret[4:12]}"

    cloud = CloudClient(server, secret)
    agent = RemoteAcpAgent(
        cloud=cloud,
        expert_id=expert,
        credential_id=credential_id,
        store=SessionStore(sessions_path),
    )
    try:
        await run_agent(agent, use_unstable_protocol=True)
    finally:
        await cloud.aclose()
