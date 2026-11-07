"""Entrypoint helpers for ``octop acp-remote``."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from octop.i18n import tr
from octop.infra.acp_remote.agent import RemoteAcpAgent
from octop.infra.acp_remote.cloud import CloudClient
from octop.infra.acp_remote.sessions import SessionStore
from octop.infra.utils.locale import DEFAULT_LOCALE


def _read_token(token_file: Path | None, token: str | None) -> str:
    if token_file is not None:
        raw = token_file.read_text(encoding="utf-8").strip()
        if not raw:
            raise ValueError(tr("acp_remote.empty_token", DEFAULT_LOCALE))
        return raw
    if token:
        return token.strip()
    raise ValueError(tr("acp_remote.missing_token", DEFAULT_LOCALE))


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
    logging.basicConfig(
        level=level, stream=sys.stderr, format="%(levelname)s %(name)s: %(message)s"
    )

    secret = await asyncio.to_thread(_read_token, token_file, token)
    cloud = CloudClient(server, secret)
    try:
        identity = await cloud.identity()
        agent = RemoteAcpAgent(
            cloud=cloud,
            expert_id=expert,
            credential_id=identity["credential_id"],
            store=await asyncio.to_thread(SessionStore, sessions_path),
        )
        await run_agent(agent, use_unstable_protocol=True)
    finally:
        await cloud.aclose()
