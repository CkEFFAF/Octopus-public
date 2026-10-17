#!/usr/bin/env python3
"""Idempotent ops seed: write MCP names into devices.capability_policy_json.

Does **not** rewrite agents.mcp_servers (0025 DEC-C10).

Example:
  uv run python scripts/seed_device_capability_mcp.py \\
    --device-id main --mcp jdcloud-mon --device-id Y39HY4

Prefer the management API when the server is up:
  POST /devices/{id}/capability-policy/seed-mcp
"""

from __future__ import annotations

import argparse
import sys


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device-id", action="append", required=True)
    parser.add_argument("--mcp", action="append", default=["jdcloud-mon"])
    parser.add_argument("--owner-user-id", type=int, default=None)
    args = parser.parse_args(argv)

    from octop.config import load_config
    from octop.infra.db.factory import open_database
    from octop.infra.db.migrate import run_migrations
    from octop.infra.db.services import RepoBundle
    from octop.infra.devices.service import DeviceService
    from octop.infra.utils.paths import PathLayout

    config = load_config()
    paths = PathLayout.from_env()
    pool = open_database(config, paths)
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    service = DeviceService(repos)
    for device_id in args.device_id:
        row = repos.device_repo.get(device_id)
        if row is None:
            print(f"skip missing device {device_id}", file=sys.stderr)
            continue
        owner = args.owner_user_id or row.owner_user_id
        out = service.seed_capability_mcp(owner, device_id, list(args.mcp), actor="ops-seed")
        print(
            device_id,
            "mcp=",
            (out.get("capability_policy") or {}).get("mcp_servers"),
            "missing=",
            out.get("missing_or_unauthorized"),
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
