"""`octop acp-remote` — stdio ACP adapter to a remote Octop expert (no local server)."""

from __future__ import annotations

import asyncio
import os
from pathlib import Path

import click


@click.command("acp-remote")
@click.option("--server", default=None, help="Cloud Octop base URL (or OCTOP_ACP_SERVER)")
@click.option("--expert", default=None, help="Expert / agent id (or OCTOP_ACP_EXPERT)")
@click.option(
    "--token-file",
    type=click.Path(path_type=Path, exists=False),
    default=None,
    help="Path to file holding oaa_ secret (or OCTOP_ACP_TOKEN_FILE)",
)
@click.option("--debug", is_flag=True, default=False, help="Debug logs on stderr")
def acp_remote_cmd(
    server: str | None,
    expert: str | None,
    token_file: Path | None,
    debug: bool,
) -> None:
    """Speak ACP on stdio and call the cloud expert APIs. Does not start OctopServer."""
    server = server or os.environ.get("OCTOP_ACP_SERVER")
    expert = expert or os.environ.get("OCTOP_ACP_EXPERT")
    if token_file is None:
        env_path = os.environ.get("OCTOP_ACP_TOKEN_FILE")
        token_file = Path(env_path) if env_path else None
    token = os.environ.get("OCTOP_ACP_TOKEN")
    if not server:
        raise click.ClickException("--server or OCTOP_ACP_SERVER required")
    if not expert:
        raise click.ClickException("--expert or OCTOP_ACP_EXPERT required")
    if token_file is None and not token:
        raise click.ClickException("--token-file / OCTOP_ACP_TOKEN_FILE (or OCTOP_ACP_TOKEN) required")
    if token_file is not None and not token_file.exists():
        raise click.ClickException(f"token file not found: {token_file}")

    from octop.infra.acp_remote import run_acp_remote

    try:
        asyncio.run(
            run_acp_remote(
                server=server,
                expert=expert,
                token_file=token_file,
                token=token if token_file is None else None,
                debug=debug,
            )
        )
    except KeyboardInterrupt:
        raise SystemExit(0) from None
