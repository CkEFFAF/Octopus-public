"""Instance-scoped shared expert admission for owned team rooms."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import secrets
from typing import Any

from langgraph.config import get_config

from octop.infra.errors import ErrorCode, OctopError


def verify_shared_text_scope(manager: Any, target_id: str, owner: int, marker: Any) -> None:
    """Verify server provenance and fresh room eligibility before bypassing device defaults."""
    if not isinstance(marker, dict):
        raise OctopError(ErrorCode.FORBIDDEN, "invalid shared text scope")
    payload = {key: marker.get(key) for key in ("owner", "host", "target", "thread")}
    secret = getattr(manager, "_shared_text_secret", None)
    signature = marker.get("signature")
    expected = (
        hmac.new(secret, json.dumps(payload, sort_keys=True).encode(), hashlib.sha256).hexdigest()
        if isinstance(secret, bytes)
        else ""
    )
    if (
        not expected
        or not isinstance(signature, str)
        or not hmac.compare_digest(expected, signature)
    ):
        raise OctopError(ErrorCode.FORBIDDEN, "invalid shared text provenance")
    host, target = manager.get_row(str(payload["host"])), manager.get_row(target_id)
    user = manager._repos.user_repo.get(owner)
    thread = manager._repos.thread_repo.get(str(payload["thread"]))
    if not (
        payload["owner"] == owner
        and payload["target"] == target_id
        and user is not None
        and not user.disabled
        and host is not None
        and host.user_id == owner
        and host.kind == "team"
        and host.enabled
        and target is not None
        and target.user_id != owner
        and target.is_shared
        and target.enabled
        and target.kind == "expert"
        and target_id in manager.teams.member_ids(host.agent_id)
        and thread is not None
        and thread.user_id == owner
        and thread.agent_id == host.agent_id
    ):
        raise OctopError(ErrorCode.FORBIDDEN, "shared text collaboration is no longer authorized")


def install_shared_team_peers(manager: Any, team: Any) -> None:
    if getattr(team, "_octop_shared_peers_installed", False) is True:
        return
    original_list, original_resolve = team.list_peers, team._resolve_peer_entry
    original_invoke = team._invoke_peer
    original_build = team._build_peer_request
    if not isinstance(getattr(manager, "_shared_text_secret", None), bytes):
        manager._shared_text_secret = secrets.token_bytes(32)

    def admitted(owner: Any, host_id: str | None, target_id: str) -> bool:
        host, target = manager.get_row(host_id or ""), manager.get_row(target_id)
        user = manager._repos.user_repo.get(int(owner))
        return bool(
            user is not None
            and not user.disabled
            and host is not None
            and host.kind == "team"
            and host.user_id == int(owner)
            and host.enabled
            and target is not None
            and target.kind == "expert"
            and target.enabled
            and target.is_shared
            and target.user_id != int(owner)
            and target_id in manager.teams.member_ids(host.agent_id)
        )

    def list_peers(
        user_id: Any, *, exclude_agent_id: str | None = None, team_peers: Any = None
    ) -> list[Any]:
        peers = list(
            original_list(user_id, exclude_agent_id=exclude_agent_id, team_peers=team_peers)
        )
        host = manager.get_row(exclude_agent_id or "")
        if host is None or host.kind != "team" or host.user_id != int(user_id):
            return peers
        for target_id in manager.teams.member_ids(host.agent_id):
            if admitted(user_id, host.agent_id, target_id):
                try:
                    entry = team._registry.get(target_id)
                except KeyError:
                    continue
                if all(item.agent_id != target_id for item in peers):
                    peers.append(entry)
        allowlist = team._peer_allowlist(exclude_agent_id)
        if allowlist is not None:
            peers = team._filter_peers(peers, allowlist)
        if team_peers is None:
            from octop_harness.teams.team_manager import _request_team_peers

            team_peers = _request_team_peers()
        if team_peers is not None:
            peers = team._filter_peers(peers, team_peers)
        team._apply_peer_enrich(peers)
        return peers

    def resolve(from_agent_id: str, to_agent_id: str, user_id: Any) -> Any:
        target = manager.get_row(to_agent_id)
        if target is not None and target.user_id != int(user_id):
            if not admitted(user_id, from_agent_id, to_agent_id):
                raise ValueError("shared expert is not an enabled member of your team")
            # Reuse listing filters and recheck persisted eligibility at dispatch time.
            if not any(
                item.agent_id == to_agent_id
                for item in list_peers(user_id, exclude_agent_id=from_agent_id)
            ):
                raise ValueError("shared expert is unavailable to this team request")
            try:
                cfg = get_config().get("configurable") or {}
            except RuntimeError:
                cfg = {}
            thread_id = cfg.get("thread_id")
            if thread_id:
                thread = manager._repos.thread_repo.get(str(thread_id))
                if (
                    thread is None
                    or thread.user_id != int(user_id)
                    or thread.agent_id != from_agent_id
                ):
                    raise ValueError("shared collaboration requires your team conversation")
            # Canonical prepare validates DispatchOptions and strips all device
            # and resource authority for text-only shared collaboration.
            return team._registry.get(to_agent_id)
        return original_resolve(from_agent_id, to_agent_id, user_id)

    async def invoke(**kwargs: Any) -> Any:
        target = manager.get_row(kwargs["to_agent_id"])
        if target is None or target.user_id != int(kwargs["user_id"]):
            await asyncio.to_thread(
                resolve, kwargs["from_agent_id"], kwargs["to_agent_id"], kwargs["user_id"]
            )
        return await original_invoke(**kwargs)

    async def build(**kwargs: Any) -> Any:
        target = manager.get_row(kwargs["to_agent_id"])
        marker = None
        if target is None or target.user_id != int(kwargs["user_id"]):
            await asyncio.to_thread(
                resolve, kwargs["from_agent_id"], kwargs["to_agent_id"], kwargs["user_id"]
            )
            marker = {
                "owner": int(kwargs["user_id"]),
                "host": kwargs["from_agent_id"],
                "target": kwargs["to_agent_id"],
                "thread": kwargs.get("source_thread_id"),
            }
            marker["signature"] = hmac.new(
                manager._shared_text_secret,
                json.dumps(marker, sort_keys=True).encode(),
                hashlib.sha256,
            ).hexdigest()
            await asyncio.to_thread(
                verify_shared_text_scope, manager, target.agent_id, int(kwargs["user_id"]), marker
            )
        request = await original_build(**kwargs)
        if marker is not None:
            request.configurable = {
                **(request.configurable or {}),
                "octop_shared_text_scope": dict(marker),
            }
            request.conversation_mode = "ask"
            request.skills = []
            request.mcp_servers = []
        return request

    team.list_peers = list_peers
    team._resolve_peer_entry = resolve
    team._invoke_peer = invoke
    team._build_peer_request = build
    team._octop_shared_peers_installed = True
