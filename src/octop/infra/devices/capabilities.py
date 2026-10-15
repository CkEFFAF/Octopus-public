"""Discover device-local skills, runners and MCP names without exporting auth."""

from __future__ import annotations

import importlib.metadata
import importlib.util
import json
import os
import shutil
import time
import tomllib
from pathlib import Path
from typing import Any

from octop.infra.skills.external_sources import (
    SOURCE_DIRS,
    discover_external_skills,
    load_external_skill,
)

MAX_CONFIG = 256 * 1024


def inspect_skill(
    source: str, slug: str, expected_digest: str, home: Path | None = None
) -> dict[str, Any]:
    """Inspect one validated snapshot; the caller must match its observed digest."""
    home = home or Path.home()
    package, digest = load_external_skill(home, source, slug)
    if digest != expected_digest:
        raise ValueError("external skill changed; refresh discovery")
    manifest = next(data for name, data in package.files if name == "SKILL.md")
    return {
        "source": source,
        "slug": slug,
        "digest": digest,
        "path": str(home.joinpath(*SOURCE_DIRS[source], slug)),
        "manifest": manifest.decode("utf-8")[:32768],
        "files": [name for name, _ in package.files],
        "file_count": len(package.files),
    }


def discover(home: Path | None = None) -> dict[str, Any]:
    from octop.infra.devices.browser import browser_runtime

    home = home or Path.home()
    entries: list[dict[str, Any]] = []
    for skill in discover_external_skills(home):
        entries.append(
            {
                **{key: skill[key] for key in ("source", "slug", "digest", "file_count")},
                "id": f"skill:{skill['source']}:{skill['slug']}",
                "kind": "skill",
                "name": skill["name"][:160],
                "description": skill["description"][:512],
                "path": str(home.joinpath(*SOURCE_DIRS[skill["source"]], skill["slug"])),
                "status": "available",
                "version": None,
            }
        )
    for command in ("codex", "claude", "opencode", "git", "python", "node", "nvidia-smi"):
        executable = shutil.which(command)
        entries.append(
            {
                "id": f"cli:{command}",
                "kind": "cli",
                "source": command,
                "name": command,
                "path": executable,
                "status": "installed" if executable else "unavailable",
                "version": None,
                "reason": "CLI found; authentication and runner protocol are not probed"
                if executable
                else "executable not found on device PATH",
            }
        )
    configs = [
        ("codex", home / ".codex" / "config.toml", "mcp_servers"),
        ("claude", home / ".claude.json", "mcpServers"),
        ("opencode", home / ".config" / "opencode" / "opencode.json", "mcp"),
    ]
    for source, path, key in configs:
        if not path.is_file():
            continue
        try:
            with path.open("rb") as stream:
                raw = stream.read(MAX_CONFIG + 1)
            if len(raw) > MAX_CONFIG:
                raise ValueError("configuration exceeds discovery limit")
            config = (
                tomllib.loads(raw.decode("utf-8")) if path.suffix == ".toml" else json.loads(raw)
            )
            if not isinstance(config, dict):
                raise ValueError("invalid configuration document")
            servers = config.get(key) or {}
            if not isinstance(servers, dict):
                raise ValueError("invalid MCP section")
            for name, settings in list(servers.items())[:100]:
                if not isinstance(settings, dict):
                    continue
                mcp_command = settings.get("command")
                if isinstance(mcp_command, list):
                    mcp_command = mcp_command[0] if mcp_command else None
                binary = shutil.which(mcp_command) if isinstance(mcp_command, str) else None
                entries.append(
                    {
                        "id": f"mcp:{source}:{name}",
                        "kind": "mcp",
                        "source": source,
                        "name": str(name)[:160],
                        "path": str(path),
                        "transport": "stdio" if mcp_command else "remote",
                        "status": "configured",
                        "version": None,
                        "dependency_available": binary is not None if mcp_command else None,
                        "reason": "Only configuration presence is known; credentials, arguments and endpoint URLs remain on device",
                    }
                )
        except (ValueError, OSError, UnicodeError) as failure:
            entries.append(
                {
                    "id": f"configuration:{source}",
                    "kind": "configuration",
                    "source": source,
                    "name": source,
                    "path": str(path),
                    "status": "unavailable",
                    "reason": type(failure).__name__,
                    "version": None,
                }
            )
    packages: dict[str, str | None] = {}
    for name in ("playwright", "mcp", "pywinpty", "ptyprocess"):
        try:
            packages[name] = importlib.metadata.version(name)
        except importlib.metadata.PackageNotFoundError:
            packages[name] = None
    return {
        "entries": entries,
        "observed_at": time.time(),
        "os_user": os.environ.get("USERNAME") or os.environ.get("USER"),
        "dependencies": packages,
        "browser_dependency": importlib.util.find_spec("playwright") is not None,
        "browser_runtime": browser_runtime(),
    }
