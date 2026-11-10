"""Resolve mutable capabilities at model and tool boundaries, without graph replacement."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import sys
from collections import OrderedDict
from collections.abc import Awaitable, Callable
from functools import lru_cache
from typing import Any, cast

from langchain.agents.middleware import AgentMiddleware, ModelRequest, ModelResponse
from langchain.agents.middleware.types import AgentState
from langchain_core.messages import ToolMessage
from langgraph.prebuilt.tool_node import ToolCallRequest

from octop.infra.agents.teams.collaboration import runtime_config
from octop.infra.connectors.builder import build_http_mcp_spec
from octop.infra.connectors.catalog import get_catalog_entry, is_inprocess_gateway
from octop.infra.connectors.gateway.langchain import build_gateway_langchain_tools
from octop.infra.metrics import PERFORMANCE
from octop.infra.utils.frontmatter import parse_frontmatter

logger = logging.getLogger(__name__)


@lru_cache(maxsize=256)
def _manifest_meta(text: str) -> dict[str, Any]:
    return parse_frontmatter(text)[0]


def _change_time(fd: int, info: os.stat_result) -> int | None:
    if sys.platform != "win32":
        return info.st_ctime_ns
    # Windows st_ctime is creation time. FileBasicInfo supplies ChangeTime,
    # including edits whose writer restores the previous LastWriteTime.
    # https://learn.microsoft.com/windows/win32/api/winbase/ns-winbase-file_basic_info
    import ctypes
    import msvcrt
    from ctypes import wintypes

    class BasicInfo(ctypes.Structure):
        _fields_ = [
            ("created", ctypes.c_int64),
            ("accessed", ctypes.c_int64),
            ("written", ctypes.c_int64),
            ("changed", ctypes.c_int64),
            ("attributes", wintypes.DWORD),
        ]

    query = ctypes.WinDLL("kernel32", use_last_error=True).GetFileInformationByHandleEx
    query.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
    query.restype = wintypes.BOOL
    basic = BasicInfo()
    if not query(msvcrt.get_osfhandle(fd), 0, ctypes.byref(basic), ctypes.sizeof(basic)):
        return None
    return int(basic.changed) or None


def _local_manifest_version(workspace: Any, path: str) -> tuple[Any, ...] | None:
    """Only authoritative local files have a version; remote materializations do not."""
    from deepagents.backends.filesystem import FilesystemBackend
    from octop_harness.backends.workspace import BackendWorkspace

    if type(workspace) is not BackendWorkspace or type(workspace.backend) is not FilesystemBackend:
        return None
    try:
        local = workspace.materialize_local(path)
        if local is None:
            return None
        # Opening also rechecks current OS read access without rereading the body.
        with local.open("rb") as source:
            info = os.fstat(source.fileno())
            changed = _change_time(source.fileno(), info)
        if changed is None:
            return None
        return (
            str(local),
            info.st_dev,
            info.st_ino,
            info.st_size,
            info.st_mtime_ns,
            changed,
            info.st_mode,
        )
    except OSError:
        return None


def _tool_name(tool: Any) -> str:
    if isinstance(tool, str):
        return tool
    if isinstance(tool, dict):
        return str((tool.get("function") or {}).get("name") or tool.get("name") or "")
    return str(getattr(tool, "name", ""))


def _key(agent_id: str, cfg: dict[str, Any]) -> tuple[int, str, str, str] | None:
    owner = int(cfg.get("user") or 0)
    thread = str(cfg.get("thread_id") or "")
    run = str(cfg.get("octop_task_run_id") or "")
    return (owner, agent_id, thread, run) if owner and thread and run else None


def remember_self_update(manager: Any, agent_id: str, names: list[str]) -> bool:
    cfg = runtime_config()
    identity = _key(agent_id, cfg)
    if identity is None or cfg.get("agent_id") != agent_id:
        return False
    row = manager.get_row(agent_id)
    if row is None or row.user_id != identity[0]:
        return False
    updates = getattr(manager, "_live_connector_selections", None)
    if updates is None:
        updates = OrderedDict()
        manager._live_connector_selections = updates
    updates[identity] = list(names)
    updates.move_to_end(identity)
    while len(updates) > 512:
        updates.popitem(last=False)
    return True


class LiveConfigurationMiddleware(AgentMiddleware[Any, Any]):
    def __init__(self, manager: Any, agent_id: str) -> None:
        self.manager = manager
        self.agent_id = agent_id
        self._known_names: set[str] = set()
        self._gateway_tools: OrderedDict[tuple[str, str, str, str], list[Any]] = OrderedDict()
        self._manifest_workspace: Any = None
        self._manifests: OrderedDict[str, tuple[tuple[Any, ...], dict[str, Any]]] = OrderedDict()

    def _selection(self, cfg: dict[str, Any]) -> list[str]:
        return self.resolve_selection(cfg)

    def resolve_selection(
        self, cfg: dict[str, Any], *, explicit: list[str] | None = None
    ) -> list[str]:
        """Resolve the same scoped choices for live tools and explicit attachment."""
        owner = int(cfg.get("user") or 0)
        row = self.manager.get_row(self.agent_id)
        if not owner or row is None or cfg.get("octop_shared_text_scope") is not None:
            return []
        user = self.manager._repos.user_repo.get(owner)
        if user is None or user.disabled:
            return []
        from octop.infra.agents.teams import is_team_agent

        modes = {cfg.get("conversation_mode"), cfg.get("work_mode")}
        if is_team_agent(row) or modes & {"ask", "plan"}:
            return []
        updates = getattr(self.manager, "_live_connector_selections", {})
        selection = (
            explicit
            if explicit is not None
            else updates.get(_key(self.agent_id, cfg), cfg.get("mcp_servers"))
        )
        execution = cfg.get("octop_execution_context") or {}
        if "device_id" in execution and not execution["device_id"]:
            defaults, denied = [], []
        else:
            defaults, denied, _ = self.manager.device_mcp_pack_for_turn(
                owner,
                agent_id=self.agent_id,
                thread_id=cfg.get("thread_id"),
                resolved_device_id=execution.get("device_id"),
            )
        explicit = selection if isinstance(selection, list) else None
        names = self.manager.merge_turn_mcp_servers(
            owner,
            explicit,
            apply_defaults=explicit is None,
            extra_defaults=self.manager.default_mcp_servers(self.agent_id),
            device_defaults=defaults,
            deny_mcp_servers=denied,
        )
        return list(names or [])

    async def _tools(self, cfg: dict[str, Any]) -> list[Any]:
        owner = int(cfg.get("user") or 0)
        names = self._selection(cfg)
        if not names:
            return []
        service = self.manager._connector_svc
        visible = {
            item.mcp_server_name: item
            for item in self.manager._repos.connector_repo.list_visible(owner)
            if item.status == "active" and item.has_credentials
        }
        custom = service.custom_harness_configs(owner)
        disabled = set(self.manager.get_config(self.agent_id).get("tools_disabled") or [])
        tools: list[Any] = []
        for name in names:
            try:
                item = visible.get(name)
                if item is not None:
                    entry = get_catalog_entry(item.kind)
                    if entry is None:
                        continue
                    creds = await service.ensure_fresh_credentials(item.instance_id, item.kind)
                    if not creds:
                        continue
                    if is_inprocess_gateway(entry):
                        fingerprint = hashlib.sha256(
                            json.dumps(creds, sort_keys=True, default=str).encode()
                        ).hexdigest()
                        key = (item.instance_id, name, item.kind, fingerprint)
                        loaded = self._gateway_tools.get(key)
                        PERFORMANCE.cache("gateway_schema", hit=loaded is not None)
                        if loaded is None:
                            loaded = build_gateway_langchain_tools(
                                entry=entry,
                                instance_id=item.instance_id,
                                mcp_server_name=name,
                                creds=creds,
                            )
                            self._gateway_tools[key] = loaded
                        self._gateway_tools.move_to_end(key)
                        while len(self._gateway_tools) > 32:
                            self._gateway_tools.popitem(last=False)
                    else:
                        spec = build_http_mcp_spec(
                            entry=entry,
                            instance_id=item.instance_id,
                            creds=creds,
                            config=self.manager._config,
                        )
                        loaded = await self.manager._get_or_load_mcp_tools(owner, name, spec)
                elif name in custom:
                    loaded = await self.manager._get_or_load_mcp_tools(owner, name, custom[name])
                else:
                    continue
                for tool in loaded:
                    if tool.name not in disabled:
                        tools.append(
                            tool.model_copy(
                                update={"extras": {**(tool.extras or {}), "defer_loading": True}}
                            )
                        )
            except Exception as exc:
                logger.warning("Live connector resolution failed (%s)", type(exc).__name__)
        self._known_names.update(tool.name for tool in tools)
        return tools

    async def _skills(self, cfg: dict[str, Any]) -> list[dict[str, Any]]:
        if {cfg.get("conversation_mode"), cfg.get("work_mode")} & {"ask", "plan"} or cfg.get(
            "octop_shared_text_scope"
        ) is not None:
            return []
        from octop_harness.backends.execution import StorageExecutionBackend

        self.manager.sync_skill_package_dirs(self.agent_id, refresh_graph=False)
        agent = self.manager.get_agent(self.agent_id)
        workspace = agent.workspace
        if workspace is not self._manifest_workspace:
            self._manifests.clear()
            self._manifest_workspace = workspace
        disabled = set(self.manager.get_config(self.agent_id).get("skills_disabled") or [])
        selected = cfg.get("skills")
        manifests: list[tuple[str, str, str]] = []
        for root, _ in workspace.skill_catalog_roots(extra=agent.config.skills_dir):
            listing = await workspace.als(root)
            for item in getattr(listing, "entries", ()) or ():
                path = item.get("path") if isinstance(item, dict) else getattr(item, "path", "")
                is_dir = (
                    item.get("is_dir") if isinstance(item, dict) else getattr(item, "is_dir", False)
                )
                slug = str(path).replace("\\", "/").rstrip("/").rsplit("/", 1)[-1]
                if not is_dir or not slug or slug.startswith("."):
                    continue
                manifest_path = f"{str(root).rstrip('/')}/{slug}/SKILL.md"
                manifests.append((str(root), manifest_path, slug))
        capacity = asyncio.Semaphore(4)

        async def read_manifest(manifest: tuple[str, str, str]) -> dict[str, Any] | None:
            root, manifest_path, slug = manifest
            async with capacity:
                version = await asyncio.to_thread(_local_manifest_version, workspace, manifest_path)
                cached = self._manifests.get(manifest_path)
                hit = version is not None and cached is not None and cached[0] == version
                PERFORMANCE.cache("skill_manifest", hit=hit)
                if hit and cached is not None:
                    meta = cached[1]
                    self._manifests.move_to_end(manifest_path)
                else:
                    self._manifests.pop(manifest_path, None)
                    text = await workspace.aread_text(manifest_path)
                    if not text or not text.startswith(("---\n", "---\r\n")):
                        return None
                    fence = text.find("\n---", 3)
                    header = text[: fence + 4] if fence >= 0 else text
                    meta = (
                        _manifest_meta(header)
                        if len(header) <= 32_768
                        else parse_frontmatter(text)[0]
                    )
                    if version is not None and len(header) <= 32_768:
                        self._manifests[manifest_path] = (version, meta)
                        while len(self._manifests) > 256:
                            self._manifests.popitem(last=False)
            name, description = meta.get("name"), meta.get("description")
            if not isinstance(name, str) or not isinstance(description, str):
                return None
            if not name.strip() or not description.strip() or meta.get("removed"):
                return None
            storage_backend = getattr(agent.config, "execution_backend", None) is not None
            allowed = meta.get("allowed-tools")
            allowed_tools = (
                allowed.split()
                if isinstance(allowed, str)
                else [value for value in allowed if isinstance(value, str)]
                if isinstance(allowed, list)
                else []
            )
            metadata = meta.get("metadata")
            return {
                "name": name,
                "description": description[:1024],
                "allowed_tools": allowed_tools,
                "license": str(meta.get("license") or "").strip() or None,
                "compatibility": str(meta.get("compatibility") or "").strip()[:500] or None,
                "metadata": (
                    {str(key): str(value) for key, value in metadata.items()}
                    if isinstance(metadata, dict)
                    else {}
                ),
                "path": (
                    StorageExecutionBackend.storage_path(manifest_path)
                    if storage_backend
                    else manifest_path
                ),
                "source": (
                    StorageExecutionBackend.storage_path(str(root))
                    if storage_backend
                    else str(root)
                ),
                "slug": slug,
            }

        merged: dict[str, dict[str, Any]] = {}
        for metadata in await asyncio.gather(*(read_manifest(item) for item in manifests)):
            if metadata is not None:
                merged[metadata["name"]] = metadata
        return [
            item
            for name, item in merged.items()
            if name not in disabled
            and item["slug"] not in disabled
            and (selected is None or name in selected or item["slug"] in selected)
        ]

    async def _prepare(self, request: ModelRequest[Any], cfg: dict[str, Any]) -> ModelRequest[Any]:
        if not cfg.get("user"):
            return request
        agent = self.manager.get_agent(self.agent_id)
        old_names = set(getattr(agent, "_mcp_tool_name_set", ())) | self._known_names
        tools = await self._tools(cfg)
        names = {tool.name for tool in tools}
        retained = [tool for tool in request.tools if _tool_name(tool) not in old_names | names]
        with PERFORMANCE.measure("skill_refresh"):
            skills = await self._skills(cfg)
        state = cast(AgentState[Any], {**request.state, "skills_metadata": skills})
        return request.override(tools=[*retained, *tools], state=state)

    def wrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], ModelResponse[Any]],
    ) -> ModelResponse[Any]:
        return handler(asyncio.run(self._prepare(request, runtime_config())))

    async def awrap_model_call(
        self,
        request: ModelRequest[Any],
        handler: Callable[[ModelRequest[Any]], Awaitable[ModelResponse[Any]]],
    ) -> ModelResponse[Any]:
        return await handler(await self._prepare(request, runtime_config()))

    async def awrap_tool_call(
        self, request: ToolCallRequest, handler: Callable[..., Awaitable[Any]]
    ) -> Any:
        cfg = runtime_config()
        agent = self.manager.get_agent(self.agent_id)
        tools = {tool.name: tool for tool in await self._tools(cfg)}
        name = request.tool_call["name"]
        if name in tools:
            return await handler(request.override(tool=tools[name]))
        if name in set(getattr(agent, "_mcp_tool_name_set", ())) | self._known_names:
            return ToolMessage(
                "Connector tool is not available in this conversation's current configuration.",
                tool_call_id=request.tool_call["id"],
                status="error",
            )
        return await handler(request)

    def wrap_tool_call(self, request: ToolCallRequest, handler: Callable[..., Any]) -> Any:
        agent = self.manager.get_agent(self.agent_id)
        tools = {tool.name: tool for tool in asyncio.run(self._tools(runtime_config()))}
        name = request.tool_call["name"]
        if name in tools:
            return handler(request.override(tool=tools[name]))
        if name in set(getattr(agent, "_mcp_tool_name_set", ())) | self._known_names:
            return ToolMessage(
                "Connector tool is not available in this conversation's current configuration.",
                tool_call_id=request.tool_call["id"],
                status="error",
            )
        return handler(request)
