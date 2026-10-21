"""Product operations on the same resources used by the dashboard."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import TYPE_CHECKING, Any, cast

from langchain_core.tools import StructuredTool
from langgraph.config import get_config
from pydantic import BaseModel

from octop.infra.agents.settings.profile import dump_id_list, id_list_from_row
from octop.infra.agents.settings.tool_catalog import BUILTIN_TOOL_CATALOG, CRITICAL_TOOLS
from octop.infra.agents.subagents.service import (
    catalog_content,
    custom_definition,
    subagent_path,
    write_definition,
)
from octop.infra.agents.teams.target_visibility import visible_expert_defaults
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.gateway.threads import ThreadRegistry
from octop.infra.utils.locale import normalize_locale, resolve_user_locale
from octop.infra.utils.ulid import new_ulid

if TYPE_CHECKING:
    from octop.infra.history.sharing import ThreadSharingService


def message_text(wire: Any, *, limit: int = 4000) -> tuple[str, bool]:
    """Only visible text; never tool calls, reasoning, attachments or metadata."""
    if isinstance(wire, str):
        try:
            wire = json.loads(wire)
        except (ValueError, TypeError):
            return "", False
    if not isinstance(wire, dict):
        return "", False
    data = wire.get("data", wire)
    content = data.get("content") if isinstance(data, dict) else None
    if isinstance(content, str):
        return content[:limit], len(content) > limit
    if isinstance(content, list):
        text = "\n".join(
            part["text"]
            for part in content
            if isinstance(part, dict)
            and part.get("type") == "text"
            and isinstance(part.get("text"), str)
        )
        return text[:limit], len(text) > limit
    return "", False


def build_native_management_tools(
    manager: Any,
    repos: Any,
    agent_id: str,
    *,
    catalog: Any = None,
    history_archive: Any = None,
    turn_active: Any = None,
    execution: Any = None,
    sharing: ThreadSharingService | None = None,
) -> list[Any]:
    """Bind resources, obtaining the acting account afresh from trusted run config."""
    tools: list[Any] = []

    def identity(*, writes: bool = False) -> Any:
        cfg = get_config().get("configurable") or {}
        uid = int(cfg.get("user") or 0)
        user = repos.user_repo.get(uid) if uid > 0 else None
        if user is None or user.disabled:
            raise OctopError(ErrorCode.FORBIDDEN, "authenticated active user required")
        context = cfg.get("octop_execution_context") or {}
        modes = {cfg.get("conversation_mode"), cfg.get("work_mode"), context.get("work_mode")}
        if writes and modes & {"ask", "plan"}:
            raise OctopError(ErrorCode.FORBIDDEN, "this mode permits observation only")
        return user

    def operation(
        *, writes: bool = False
    ) -> Callable[[Callable[..., Awaitable[dict[str, Any]]]], Callable[..., Awaitable[str]]]:
        def decorate(
            func: Callable[..., Awaitable[dict[str, Any]]],
        ) -> Callable[..., Awaitable[str]]:
            @wraps(func)
            async def invoke(**kwargs: Any) -> str:
                try:
                    user = identity(writes=writes)
                    if func.__name__ in manager.get_config(agent_id).get("tools_disabled", []):
                        raise OctopError(ErrorCode.FORBIDDEN, "tool is disabled for this expert")
                    value = await func(**kwargs)
                    repos.audit_repo.write(
                        actor=f"agent:{agent_id}:user:{user.id}",
                        action=func.__name__,
                        target=str(
                            value.get("instance_id")
                            or value.get("agent_id")
                            or value.get("thread_id")
                            or agent_id
                        ),
                        payload=json.dumps({"status": "saved" if writes else "read"}),
                    )
                    return json.dumps(value, ensure_ascii=False)
                except (OctopError, ValueError, TypeError) as exc:
                    cfg = get_config().get("configurable") or {}
                    repos.audit_repo.write(
                        actor=f"agent:{agent_id}:user:{cfg.get('user') or 0}",
                        action=func.__name__,
                        target=agent_id,
                        payload=json.dumps({"status": "denied_or_failed"}),
                    )
                    envelope = (
                        exc.to_envelope() if isinstance(exc, OctopError) else {"error": str(exc)}
                    )
                    if func.__name__.startswith("octop_connector_"):
                        from octop.infra.connectors.credentials import redact_credential_values

                        kind = kwargs.get("kind") or ""
                        instance = repos.connector_repo.get(kwargs.get("instance_id") or "")
                        if instance is not None and instance.user_id == cfg.get("user"):
                            kind = instance.kind
                            envelope = redact_credential_values(
                                envelope,
                                manager._connector_svc.decrypt(instance.instance_id),
                                kind=kind,
                            )
                        envelope = redact_credential_values(
                            envelope, kwargs.get("credentials") or {}, kind=kind
                        )
                    if func.__name__.startswith("octop_mcp_"):
                        from octop.infra.agents.native_extension_tools import redact_mcp_result

                        user = repos.user_repo.get(int(cfg.get("user") or 0))
                        if user is not None and not user.disabled:
                            stored = manager._connector_svc.get_custom_servers(user.id).get(
                                kwargs.get("name")
                            )
                            if isinstance(stored, dict):
                                envelope = redact_mcp_result(envelope, stored)
                        envelope = redact_mcp_result(envelope, kwargs.get("server") or {})
                    return json.dumps(envelope, ensure_ascii=False)

            tool = StructuredTool.from_function(coroutine=invoke)
            schema = cast(type[BaseModel], tool.args_schema)
            schema.model_config["extra"] = "forbid"
            schema.model_rebuild(force=True)
            tools.append(tool)
            return invoke

        return decorate

    def owned(target: str = "", *, kind: str | None = None) -> Any:
        user = identity()
        row = manager.get_row(target or agent_id)
        if row is None or row.user_id != user.id or (kind is not None and row.kind != kind):
            raise OctopError(ErrorCode.FORBIDDEN, "owned resource required")
        return row

    def thread(thread_id: str) -> Any:
        user = identity()
        row = repos.thread_repo.get(thread_id)
        if row is None or row.user_id != user.id:
            raise OctopError(ErrorCode.FORBIDDEN, "owned conversation required")
        accessible(row.agent_id)
        return row

    def accessible(target: str = "") -> Any:
        row = manager.get_row(target or agent_id)
        if row is None or (row.user_id != identity().id and (not row.is_shared or not row.enabled)):
            raise OctopError(ErrorCode.FORBIDDEN, "expert unavailable")
        return row

    def visible_experts() -> list[Any]:
        user = identity()
        rows = [
            *manager.list_agents(user.id),
            *repos.agent_repo.list_shared(exclude_user_id=user.id),
        ]
        return [row for row in rows if row.kind == "expert"]

    def expert_payload(row: Any, *, detail: bool = False) -> dict[str, Any]:
        writable = row.user_id == identity().id
        payload = {
            "agent_id": row.agent_id,
            "name": row.name,
            "description": row.description,
            "state": row.last_state,
            "enabled": bool(row.enabled),
            "writable": writable,
            **visible_expert_defaults(row, identity().id, repos.device_repo),
        }
        if detail and writable:
            cfg = manager.get_config(row.agent_id)
            payload.update(
                default_model=row.default_model,
                system_prompt=row.system_prompt,
                welcome_message=row.welcome_message,
                skill_package_ids=id_list_from_row(row, "skill_package_ids"),
                knowledge_base_ids=id_list_from_row(row, "knowledge_base_ids"),
                mcp_servers=id_list_from_row(row, "mcp_servers"),
                tools_disabled=cfg.get("tools_disabled", []),
            )
        return payload

    def reload_status(target: str) -> dict[str, str]:
        return {
            "reload_status": "pending_current_turn"
            if manager.is_agent_active(target)
            else "scheduled"
        }

    def schedule_reload(target: str) -> dict[str, str]:
        manager.schedule_reload(target)
        return reload_status(target)

    def validate_fields(values: dict[str, Any], target: str | None = None) -> dict[str, Any]:
        user = identity()
        allowed = {
            "name",
            "description",
            "default_model",
            "system_prompt",
            "welcome_message",
            "skill_package_ids",
            "knowledge_base_ids",
            "mcp_servers",
            "tools_disabled",
            "device_binding",
        }
        fields = {
            key: value for key, value in values.items() if key in allowed and value is not None
        }
        if "device_binding" in fields:
            if execution is None:
                raise OctopError(ErrorCode.FORBIDDEN, "execution service unavailable")
            fields["device_binding"] = execution.validate_expert_binding(
                user.id, fields["device_binding"]
            )
        for key, maximum in (
            ("name", 80),
            ("description", 500),
            ("system_prompt", 32_000),
            ("welcome_message", 4000),
        ):
            if key in fields:
                value = fields[key]
                if len(value) > maximum or (key == "name" and not value.strip()):
                    raise ValueError(f"invalid {key}: maximum {maximum} characters")
                if key == "name":
                    fields[key] = value.strip()
        if "default_model" in fields:
            model = fields["default_model"].strip()
            if (
                model
                and model != "auto"
                and not manager.providers_for_user(user.id).is_model_ref_usable(model)
            ):
                raise ValueError("model must be an enabled model from your providers, or auto")
            fields["default_model"] = model if model and model != "auto" else None
        if "skill_package_ids" in fields:
            fields["skill_package_ids"] = manager.validate_skill_package_ids(
                fields["skill_package_ids"]
            )
            if fields["skill_package_ids"]:
                manager.assert_backend_supports_skill_packages(
                    manager.resolved_backend_spec(target) if target else None,
                    workspace_dir=manager.resolve_workspace_dir(target) if target else None,
                )
        if "knowledge_base_ids" in fields:
            fields["knowledge_base_ids"] = manager.validate_knowledge_base_ids(
                user.id, fields["knowledge_base_ids"]
            )
        if "mcp_servers" in fields:
            fields["mcp_servers"] = manager.validate_mcp_servers(user.id, fields["mcp_servers"])
        if "tools_disabled" in fields:
            names = set(fields["tools_disabled"])
            if names - {entry.name for entry in BUILTIN_TOOL_CATALOG} or names & CRITICAL_TOOLS:
                raise ValueError("unknown or critical tool cannot be disabled")
            fields["tools_disabled"] = sorted(names)
        return fields

    def thread_payload(row: Any) -> dict[str, Any]:
        return {
            "thread_id": row.thread_id,
            "agent_id": row.agent_id,
            "title": row.title,
            "last_active": row.last_active,
            "created_at": row.created_at,
            "pinned": row.pinned,
            "history_status": repos.thread_message_repo.projection_status(row.thread_id),
        }

    def create_thread(target: Any, title: str) -> dict[str, Any]:
        if len(title) > 200:
            raise ValueError("conversation title is too long")
        uid = identity().id
        tid = f"thr_{new_ulid()}"
        repos.thread_repo.insert(
            thread_id=tid,
            agent_id=target.agent_id,
            user_id=uid,
            channel_type=ThreadRegistry.CHANNEL_DASHBOARD,
            session_key=ThreadRegistry.dashboard_key(agent_id=target.agent_id, user_id=uid),
            title=title.strip() or None,
            last_active=0,
        )
        return {"thread_id": tid, "agent_id": target.agent_id}

    @operation()
    async def octop_capabilities() -> dict[str, Any]:
        """Discover available native product tools, parameters and existing task/device tools."""
        current = manager.get_agent(agent_id)
        registered = {
            getattr(tool, "name", "") for tool in (getattr(current.config, "tools", None) or [])
        }
        registered.update(getattr(current, "_tools_by_name", {}) or {})
        if (
            getattr(current.config, "team_enabled", False)
            and getattr(current, "_team_manager", None) is not None
        ):
            registered.update({"ask_agent", "agent_list"})
        disabled = set(getattr(current.config, "tools_disabled", ()) or ())
        available = registered - disabled
        return {
            "tools": [
                {"name": tool.name, "description": tool.description, "parameters": tool.args}
                for tool in tools
                if tool.name in available
            ],
            "existing_tools": sorted(
                name
                for name in available
                if name.startswith(("task_board_", "device_", "cronjob_"))
                or name
                in {
                    "ask_agent",
                    "agent_list",
                    "work_step",
                    "schedule_self_check",
                    "cancel_self_check",
                }
            ),
            "rules": "Only owned resources can be changed. Ask/Plan are read-only. Device selection affects later turns. Team members are dispatched with ask_agent. Foreign shared members support text collaboration only; cross-account device execution is unsupported. Publish a conversation snapshot only when the user explicitly requests external sharing; preview the exact public text first and use its digest. Never publish automatically.",
        }

    from octop.infra.agents.native_connector_tools import register_connector_tools

    register_connector_tools(
        manager, repos, agent_id, identity=identity, owned=owned, operation=operation
    )

    from octop.infra.agents.native_extension_tools import register_extension_tools

    register_extension_tools(
        manager, repos, agent_id, identity=identity, owned=owned, operation=operation
    )

    @operation()
    async def octop_resource_list() -> dict[str, Any]:
        """Find model, skill, knowledge, connector and tool references without credentials.

        Connector availability means configured, not verified upstream login.
        QQ Mail uses an IMAP/SMTP app password, not browser OAuth. The Agently
        mail cron source is a different connector and cannot diagnose QQ login.
        """
        user = identity()
        store = manager.providers_for_user(user.id)
        models = [
            f"{provider.name}/{model['id']}"
            for provider in store.iter_usable_rows()
            for model in provider.get_models()
            if model.get("id") and store.is_model_ref_usable(f"{provider.name}/{model['id']}")
        ]
        return {
            "models": models[:200],
            "skill_packages": [
                {"id": row.id, "name": row.name}
                for row in repos.skill_package_repo.list_all()[:200]
            ],
            "knowledge_bases": [
                {"id": row.id, "name": row.name}
                for row in repos.knowledge_repo.list_visible(user.id)[:200]
            ],
            "mcp_servers": [
                {"name": name, "label": label}
                for name, label in manager.mcp_server_labels_for_user(user.id).items()
            ],
            "tools": [
                {"name": entry.name, "disableable": entry.name not in CRITICAL_TOOLS}
                for entry in BUILTIN_TOOL_CATALOG
            ],
        }

    @operation()
    async def octop_expert_list() -> dict[str, Any]:
        """List your experts and shared expert choices; writable marks ownership."""
        return {"experts": [expert_payload(row) for row in visible_experts()]}

    @operation()
    async def octop_expert_get(target_agent_id: str = "") -> dict[str, Any]:
        """Read an owned expert's explicit configuration, or a shared expert's public summary."""
        target = target_agent_id or agent_id
        row = next((row for row in visible_experts() if row.agent_id == target), None)
        if row is None:
            raise OctopError(ErrorCode.FORBIDDEN, "expert unavailable")
        return expert_payload(row, detail=True)

    @operation(writes=True)
    async def octop_expert_create(
        name: str,
        description: str = "",
        default_model: str | None = None,
        system_prompt: str = "",
        welcome_message: str = "",
        skill_package_ids: list[str] | None = None,
        knowledge_base_ids: list[str] | None = None,
        mcp_servers: list[str] | None = None,
        tools_disabled: list[str] | None = None,
        device_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Create an expert. device_binding sets its owned device/local default.

        For example {"target_kind":"device","device_id":"id","working_dir":"/work"}.
        To dispatch using that default choose ask_agent(target_policy="member_default");
        inherit keeps the caller's device. This does not grant new device permissions.
        """
        from octop.infra.agents.manager import AgentCreateSpec

        fields = validate_fields(locals())
        config: dict[str, Any] = {"tools_disabled": fields.pop("tools_disabled", [])}
        if "device_binding" in fields:
            config["device_binding"] = fields.pop("device_binding")
        row = await manager.create(AgentCreateSpec(user_id=identity().id, config=config, **fields))
        return {**expert_payload(row, detail=True), "saved": True}

    @operation(writes=True)
    async def octop_expert_update(
        target_agent_id: str = "",
        name: str | None = None,
        description: str | None = None,
        default_model: str | None = None,
        system_prompt: str | None = None,
        welcome_message: str | None = None,
        skill_package_ids: list[str] | None = None,
        knowledge_base_ids: list[str] | None = None,
        mcp_servers: list[str] | None = None,
        tools_disabled: list[str] | None = None,
        device_binding: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Configure your expert. device_binding sets its owned device/local default; {} clears it.

        Omitted fields stay. Connector changes to this expert also apply to the
        current conversation at its next model request. Device defaults affect later turns. For a peer dispatch on
        this device use ask_agent(target_policy="member_default") or "explicit";
        the default "inherit" deliberately keeps the caller's target.
        """
        fields = dict(locals())
        fields.pop("target_agent_id")
        row = owned(target_agent_id, kind="expert")
        fields = validate_fields(fields, row.agent_id)
        if not fields:
            raise ValueError("supply at least one configuration field")
        if "tools_disabled" in fields or "device_binding" in fields:
            cfg = manager.get_config(row.agent_id)
            for key in ("tools_disabled", "device_binding"):
                if key in fields:
                    value = fields.pop(key)
                    if key == "device_binding" and not value:
                        cfg.pop(key, None)
                    else:
                        cfg[key] = value
            fields["config_json"] = json.dumps(cfg)
        if "default_model" in fields:
            cfg = json.loads(
                fields.get("config_json") or json.dumps(manager.get_config(row.agent_id))
            )
            cfg.pop("default_model", None)
            fields["config_json"] = json.dumps(cfg)
        for key in ("skill_package_ids", "knowledge_base_ids", "mcp_servers"):
            if key in fields:
                fields[key] = dump_id_list(fields[key])
        updated = await manager.update(row.agent_id, **fields)
        capability_update = None
        if mcp_servers is not None:
            from octop.infra.agents.middleware.live_configuration import remember_self_update

            names = id_list_from_row(updated, "mcp_servers")
            if remember_self_update(manager, row.agent_id, names):
                capability_update = {"mcp_servers": names, "effective": "next_model_request"}
        return {
            **expert_payload(updated, detail=True),
            "saved": True,
            "current_conversation_update": capability_update,
            **reload_status(row.agent_id),
        }

    @operation()
    async def octop_subagent_catalog(query: str = "", limit: int = 20) -> dict[str, Any]:
        """Find bundled subagent templates by name, description or slug."""
        if catalog is None:
            raise OctopError(ErrorCode.NOT_FOUND, "subagent catalog unavailable")
        rows = catalog.list_summaries(query=query)
        return {
            "templates": [
                {"slug": row.slug, "name": row.name, "description": row.description}
                for row in rows[: max(1, min(limit, 50))]
            ],
            "has_more": len(rows) > max(1, min(limit, 50)),
        }

    @operation()
    async def octop_subagent_list(target_agent_id: str = "") -> dict[str, Any]:
        """List installed subagents for an owned expert using the harness catalog."""
        row = owned(target_agent_id, kind="expert")
        return {
            "agent_id": row.agent_id,
            "subagents": await manager.list_subagent_summaries(row.agent_id),
        }

    @operation()
    async def octop_subagent_get(slug: str, target_agent_id: str = "") -> dict[str, Any]:
        """Read an installed subagent definition from your expert workspace."""
        row = owned(target_agent_id, kind="expert")
        content = await manager.workspace_for_agent(row.agent_id).aread_text(
            subagent_path(slug), limit=50_000
        )
        if content is None:
            raise OctopError(ErrorCode.NOT_FOUND, "subagent not found")
        return {"agent_id": row.agent_id, "slug": slug, "content": content}

    @operation(writes=True)
    async def octop_subagent_install(
        slug: str,
        target_agent_id: str = "",
        locale: str = "",
        replace: bool = False,
    ) -> dict[str, Any]:
        """Install a bundled template. Existing files require explicit replace=true."""
        row = owned(target_agent_id, kind="expert")
        item = catalog.get(slug) if catalog is not None else None
        if item is None:
            raise OctopError(ErrorCode.NOT_FOUND, "subagent template not found")
        requested = (
            normalize_locale(locale)
            if locale
            else resolve_user_locale(user_repo=repos.user_repo, user_id=identity().id)
        )
        content, installed = catalog_content(item, requested)
        path = await write_definition(
            manager.workspace_for_agent(row.agent_id),
            slug,
            content,
            agent_id=row.agent_id,
            replace=replace,
        )
        return {
            "agent_id": row.agent_id,
            "path": path,
            "locale": installed,
            "requested_locale": requested,
            "saved": True,
            **schedule_reload(row.agent_id),
        }

    @operation(writes=True)
    async def octop_subagent_save(
        slug: str,
        name: str,
        description: str,
        instructions: str,
        target_agent_id: str = "",
        replace: bool = False,
    ) -> dict[str, Any]:
        """Create or explicitly replace a custom subagent's name, description and instructions."""
        row = owned(target_agent_id, kind="expert")
        path = await write_definition(
            manager.workspace_for_agent(row.agent_id),
            slug,
            custom_definition(name, description, instructions),
            agent_id=row.agent_id,
            replace=replace,
        )
        return {
            "agent_id": row.agent_id,
            "slug": slug,
            "path": path,
            "saved": True,
            **schedule_reload(row.agent_id),
        }

    @operation()
    async def octop_project_list() -> dict[str, Any]:
        """List your expert teams (group-chat projects) and real member rosters."""
        return {"projects": await asyncio.to_thread(manager.teams.list_for_user, identity().id)}

    @operation()
    async def octop_project_get(project_id: str) -> dict[str, Any]:
        """Read an owned team and its current usable members."""
        return dict(
            await asyncio.to_thread(manager.teams.team_payload, owned(project_id, kind="team"))
        )

    @operation(writes=True)
    async def octop_project_update(
        project_id: str,
        name: str | None = None,
        description: str | None = None,
        welcome_message: str | None = None,
        default_model: str | None = None,
    ) -> dict[str, Any]:
        """Rename or configure an owned group's description, welcome text and model."""
        fields = dict(locals())
        row = owned(project_id, kind="team")
        fields = validate_fields(fields, project_id)
        if not fields:
            raise ValueError("supply a configuration field")
        if "default_model" in fields:
            cfg = manager.get_config(project_id)
            cfg.pop("default_model", None)
            fields["config_json"] = json.dumps(cfg)
        row = await manager.update(project_id, **fields)
        return {
            **await asyncio.to_thread(manager.teams.team_payload, row),
            "saved": True,
            **reload_status(project_id),
        }

    @operation(writes=True)
    async def octop_project_create(
        name: str, member_ids: list[str], description: str = ""
    ) -> dict[str, Any]:
        """Create an expert team and its group conversation; invite at least two usable experts."""
        from octop.infra.agents.manager import AgentCreateSpec
        from octop.infra.agents.teams import TEAM_TEMPLATE_NAME

        fields = validate_fields({"name": name, "description": description})
        members = manager.teams.validate_member_ids(identity(), member_ids)
        row = await manager.create(
            AgentCreateSpec(
                user_id=identity().id,
                kind="team",
                template_name=TEAM_TEMPLATE_NAME,
                member_ids=members,
                mcp_servers=[],
                **fields,
            )
        )
        payload = {**await asyncio.to_thread(manager.teams.team_payload, row), "saved": True}
        try:
            payload.update(create_thread(row, name))
        except Exception:
            payload.update(
                thread_created=False,
                next_action="octop_thread_create",
                target_agent_id=row.agent_id,
            )
        return payload

    @operation(writes=True)
    async def octop_project_update_members(
        project_id: str,
        add_member_ids: list[str] | None = None,
        remove_member_ids: list[str] | None = None,
    ) -> dict[str, Any]:
        """Invite or remove experts. Busy removal and fewer than two members are rejected."""
        row = owned(project_id, kind="team")
        await asyncio.to_thread(
            manager.teams.update_members,
            identity(),
            project_id,
            add_member_ids or [],
            remove_member_ids or [],
        )
        return {
            **await asyncio.to_thread(manager.teams.team_payload, row),
            "saved": True,
            **schedule_reload(project_id),
        }

    @operation()
    async def octop_thread_list(
        target_agent_id: str = "", limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        """List owned conversations across experts, or for one expert, with bounded pagination."""
        if target_agent_id:
            accessible(target_agent_id)
        size = max(1, min(limit, 50))
        rows, more = repos.thread_repo.search_owned(
            user_id=identity().id,
            agent_id=target_agent_id or None,
            limit=size,
            offset=max(0, offset),
        )
        return {
            "threads": [thread_payload(row) for row in rows],
            "has_more": more,
            "next_offset": max(0, offset) + size if more else None,
        }

    @operation()
    async def octop_thread_search(
        query: str, target_agent_id: str = "", limit: int = 20, offset: int = 0
    ) -> dict[str, Any]:
        """Find owned chats by literal title or ready projected user/assistant text. Legacy unindexed text is not searched."""
        if not query.strip() or len(query) > 200:
            raise ValueError("query must contain 1–200 characters")
        if target_agent_id:
            accessible(target_agent_id)
        size = max(1, min(limit, 50))
        rows, more = repos.thread_repo.search_owned(
            user_id=identity().id,
            query=query,
            agent_id=target_agent_id or None,
            limit=size,
            offset=max(0, offset),
        )
        return {
            "threads": [thread_payload(row) for row in rows],
            "has_more": more,
            "next_offset": max(0, offset) + size if more else None,
            "search_scope": "titles_and_ready_projected_user_assistant_text",
            "unindexed_history_searched": False,
        }

    @operation(writes=True)
    async def octop_thread_create(target_agent_id: str = "", title: str = "") -> dict[str, Any]:
        """Create a conversation for your expert/team without changing the active chat."""
        return create_thread(accessible(target_agent_id), title)

    @operation()
    async def octop_thread_read(
        thread_id: str, limit: int = 20, cursor: str = "", offset: int = 0
    ) -> dict[str, Any]:
        """Read bounded visible user/assistant text from an owned conversation, with history readiness."""
        row = thread(thread_id)
        if cursor and history_archive is None:
            raise ValueError("projected history uses offset pagination")
        size = max(1, min(limit, 30))
        status = repos.thread_message_repo.projection_status(thread_id)
        messages: list[dict[str, Any]] = []
        more, next_cursor = False, None
        if history_archive is not None:
            from octop.infra.history.reader import read_page

            page = await read_page(
                history_archive,
                manager,
                row.agent_id,
                thread_id,
                limit=size,
                offset=max(0, offset),
                cursor=cursor or None,
            )
            wires = page["messages"]
            more, next_cursor = page["has_more"], page["next_cursor"]
        elif status == "ready":
            rows, more = repos.thread_message_repo.page(
                thread_id, limit=size, offset=max(0, offset)
            )
            wires = [json.loads(item.message_json) for item in rows]
        else:
            wires = []
        remaining = 24_000
        truncated = False
        for wire in wires:
            role = wire.get("type") or wire.get("role") if isinstance(wire, dict) else ""
            if role in {"human", "ai", "user", "assistant"}:
                text, clipped = message_text(wire, limit=min(4000, remaining))
                truncated = truncated or clipped
                if text:
                    messages.append({"role": role, "text": text})
                    remaining -= len(text)
        return {
            **thread_payload(row),
            "history_status": status,
            "history_source": "archive_reader" if history_archive is not None else "projection",
            "text_truncated": truncated,
            "text_limits": {"per_message": 4000, "total": 24_000},
            "messages": messages,
            "has_more": more,
            "next_cursor": next_cursor,
            "next_offset": max(0, offset) + size if more and not next_cursor else None,
        }

    def share_service() -> ThreadSharingService:
        if sharing is not None:
            return sharing
        from octop.config import OctopConfig
        from octop.infra.history.sharing import ThreadSharingService

        return ThreadSharingService(repos, OctopConfig(), manager, history_archive)

    def share_thread(thread_id: str) -> str:
        selected = thread_id or str((get_config().get("configurable") or {}).get("thread_id") or "")
        thread(selected)
        return selected

    @operation()
    async def octop_thread_share_preview(thread_id: str = "") -> dict[str, Any]:
        """Preview exact public text of an owned conversation; defaults to current thread.

        Ask the owner to review this text before any external sharing. Preview never publishes.
        """
        return await share_service().preview(identity().id, share_thread(thread_id))

    @operation(writes=True)
    async def octop_thread_share_create(
        preview_digest: str, expires_in_seconds: int | None = 2592000, thread_id: str = ""
    ) -> dict[str, Any]:
        """Publish ONLY when the user explicitly requests external sharing, after preview.

        Freezes reviewed text for anyone with the link. Never publish automatically.
        Use preview_digest from preview; changed history requires a new preview.
        Expiry is seconds (60..31536000), default 30 days; null means no automatic expiry.
        """
        return await share_service().create(
            identity().id, share_thread(thread_id), preview_digest, expires_in_seconds
        )

    @operation()
    async def octop_thread_share_list(
        thread_id: str = "", before: str = "", limit: int = 50
    ) -> dict[str, Any]:
        """List your share links with status and recopyable live URLs; omit thread to list all."""
        return await asyncio.to_thread(
            share_service().list,
            identity().id,
            thread_id=share_thread(thread_id) if thread_id else None,
            before=before or None,
            limit=limit,
        )

    @operation(writes=True)
    async def octop_thread_share_revoke(share_id: str) -> dict[str, Any]:
        """Close your public share link permanently; copies already saved cannot be retracted."""
        await asyncio.to_thread(share_service().revoke, identity().id, share_id)
        return {"share_id": share_id, "status": "revoked"}

    @operation()
    async def octop_thread_status(thread_id: str) -> dict[str, Any]:
        """Inspect a conversation's persisted history status and actual current turn activity."""
        return {
            **thread_payload(thread(thread_id)),
            "turn_active": turn_active(thread_id) if turn_active else None,
        }

    @operation(writes=True)
    async def octop_thread_rename(thread_id: str, title: str) -> dict[str, Any]:
        """Rename one of your existing conversations."""
        thread(thread_id)
        if not title.strip() or len(title) > 200:
            raise ValueError("title must contain 1–200 characters")
        repos.thread_repo.update_title(thread_id, title.strip())
        return thread_payload(thread(thread_id))

    if execution is not None:

        @operation(writes=True)
        async def octop_device_select(
            thread_id: str,
            target_kind: str,
            device_id: str | None = None,
            working_dir: str | None = None,
        ) -> dict[str, Any]:
            """Select a later-turn device for your expert or team room; defaults and current context stay unchanged. Clear with target_kind=device and device_id omitted."""
            conversation = thread(thread_id)
            expert = owned(conversation.agent_id)
            selected = execution.save_selection(
                identity().id,
                thread_id,
                {"target_kind": target_kind, "device_id": device_id, "working_dir": working_dir},
            )
            return {
                "thread_id": thread_id,
                "selection": selected,
                "effective": "next_turn",
                "current_context_unchanged": True,
                "scope": "team_room" if expert.kind == "team" else "conversation",
                "expert_defaults_unchanged": True,
            }

    # --- Context Insights (spec 0020; read-only; shared service) ---
    from octop.infra.context_insights.service import ContextInsightsService

    insights = ContextInsightsService(manager, repos, execution=execution)

    def _insights_thread(thread_id: str = "") -> tuple[Any, str]:
        cfg = get_config().get("configurable") or {}
        tid = (thread_id or "").strip() or str(cfg.get("thread_id") or "").strip()
        if not tid:
            raise ValueError("thread_id is required")
        row = thread(tid)
        return row, tid

    @operation()
    async def context_inspect(
        thread_id: str = "",
        include: list[str] | None = None,
        trend_limit: int = 20,
    ) -> dict[str, Any]:
        """Read-only context window inspect (stats/breakdown/trend/execution). Spec name: context.inspect."""
        row, tid = _insights_thread(thread_id)
        user = identity()
        return await insights.inspect(
            owner=user.id,
            agent_id=row.agent_id,
            thread_id=tid,
            include=include,
            trend_limit=trend_limit,
        )

    @operation()
    async def context_events(
        thread_id: str = "",
        kinds: list[str] | None = None,
        before_seq: int | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Read-only mapped context events. Spec name: context.events."""
        row, tid = _insights_thread(thread_id)
        user = identity()
        return await insights.events(
            owner=user.id,
            agent_id=row.agent_id,
            thread_id=tid,
            kinds=kinds,
            before_seq=before_seq,
            limit=limit,
        )

    @operation()
    async def context_file_ops(
        thread_id: str = "",
        upto_request_seq: int | None = None,
        path_prefix: str = "",
        limit: int = 50,
    ) -> dict[str, Any]:
        """Read-only file activity path counts (no file bodies). Spec name: context.file_ops."""
        row, tid = _insights_thread(thread_id)
        user = identity()
        return await insights.file_ops(
            owner=user.id,
            agent_id=row.agent_id,
            thread_id=tid,
            upto_request_seq=upto_request_seq,
            path_prefix=path_prefix or None,
            limit=limit,
        )

    @operation()
    async def context_request(
        request_id: str,
        thread_id: str = "",
        include_content: bool = False,
        cursor: int | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Read retained model-request composition (DEC-T16). Spec name: context.request."""
        row, tid = _insights_thread(thread_id)
        user = identity()
        rid = (request_id or "").strip()
        if not rid:
            raise ValueError("request_id is required")
        return await insights.request(
            owner=user.id,
            agent_id=row.agent_id,
            thread_id=tid,
            request_id=rid,
            include_content=bool(include_content),
            cursor=cursor,
            limit=limit,
        )

    @operation()
    async def context_trace_read(
        event_id: str,
        thread_id: str = "",
        part: str = "all",
        cursor: int | None = None,
        limit: int = 50,
    ) -> dict[str, Any]:
        """Page authorized trajectory args/result/injection (DEC-T16). Spec name: context.trace_read."""
        row, tid = _insights_thread(thread_id)
        user = identity()
        eid = (event_id or "").strip()
        if not eid:
            raise ValueError("event_id is required")
        return await insights.trace_read(
            owner=user.id,
            agent_id=row.agent_id,
            thread_id=tid,
            event_id=eid,
            part=part or "all",
            cursor=cursor,
            limit=limit,
        )

    return tools
