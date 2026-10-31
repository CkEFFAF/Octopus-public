"""Native discovery and extension of skills, plugin tools and custom MCP servers."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qsl, urlsplit

from langgraph.config import get_config

from octop.infra.agents.native_tool_types import NativeOperation
from octop.infra.agents.plugins.plugin_tool_defaults import (
    agent_plugin_enabled,
    merge_plugins_enabled_settings,
    merge_plugins_tool_settings,
)
from octop.infra.agents.settings.tool_catalog import (
    BUILTIN_TOOL_CATALOG,
    CRITICAL_TOOLS,
    builtin_tool_available,
)
from octop.infra.agents.teams import is_team_agent
from octop.infra.connectors.credentials import redact_credential_values
from octop.infra.connectors.probe import probe_custom_mcp_server
from octop.infra.errors import ErrorCode, OctopError
from octop.infra.skills.install import (
    SkillAlreadyExistsError,
    commit_skill_install,
    prepare_skillhub_package,
    resolve_url_import,
)
from octop.infra.skills.skill_packages import validate_skill_slug
from octop.infra.skills.skillhub_market import download_skillhub_package, search_skillhub
from octop.infra.skills.workspace_install import AgentWorkspaceSkillTarget


def mcp_secret_values(spec: dict[str, Any]) -> list[str]:
    """Treat connection arguments and endpoints as sensitive in probe/error output."""
    values: list[str] = []

    def collect(item: Any) -> None:
        if isinstance(item, dict):
            for value in item.values():
                collect(value)
        elif isinstance(item, list):
            for value in item:
                collect(value)
        elif isinstance(item, str) and item:
            values.append(item)

    for key in ("headers", "env", "oauth", "args", "url"):
        collect(spec.get(key))
    secrets = list(values)
    for value in values:
        if value.lower().startswith(("bearer ", "basic ")):
            secrets.append(value.split(" ", 1)[1])
        if value.startswith("--") and "=" in value:
            secrets.append(value.split("=", 1)[1])
    if isinstance(spec.get("url"), str):
        try:
            parsed = urlsplit(spec["url"])
            secrets.extend(value for _key, value in parse_qsl(parsed.query))
            if parsed.password:
                secrets.append(parsed.password)
        except ValueError:
            pass
    return sorted(set(secrets), key=len, reverse=True)


def redact_mcp_result(value: Any, spec: dict[str, Any]) -> Any:
    for secret in mcp_secret_values(spec):
        if secret:
            value = redact_credential_values(value, {"token": secret}, kind="")
    return value


def register_extension_tools(
    manager: Any,
    repos: Any,
    agent_id: str,
    *,
    identity: Callable[..., Any],
    owned: Callable[..., Any],
    operation: NativeOperation,
) -> None:
    def guard(*, writes: bool = False, module: str = "") -> Any:
        user = identity(writes=writes)
        cfg = get_config().get("configurable") or {}
        if cfg.get("octop_shared_text_scope") is not None:
            raise OctopError(
                ErrorCode.FORBIDDEN, "extensions are unavailable in shared-text collaboration"
            )
        if module and user.role != "admin" and module not in user.permissions:
            raise OctopError(
                ErrorCode.FORBIDDEN,
                f"{module} management permission required; administrator role is not required",
            )
        return user

    def expert(target: str = "", *, writes: bool = False) -> Any:
        guard(writes=writes)
        row = owned(target, kind="expert")
        if is_team_agent(row):
            raise OctopError(ErrorCode.FORBIDDEN, "team host capabilities are fixed")
        return row

    def receipt(target: str, *, reload: bool = False, **fields: Any) -> dict[str, Any]:
        if reload:
            manager.schedule_reload(target)
        return {
            "agent_id": target,
            "saved": True,
            "effective": "after_current_turn" if reload else "next_model_request",
            "reload_status": (
                "pending_current_turn" if manager.is_agent_active(target) else "scheduled"
            )
            if reload
            else "not_required",
            **fields,
        }

    def plugin_manager() -> Any:
        mgr = manager._plugin_manager
        if mgr is None:
            raise ValueError("plugin manager is unavailable")
        return mgr

    def installed_plugin(plugin_id: str) -> dict[str, Any]:
        item = next(
            (
                item
                for item in plugin_manager().list_installed()
                if item.get("id") == plugin_id and not item.get("error")
            ),
            None,
        )
        if item is None:
            raise ValueError("installed plugin not found; discover/install it first")
        return dict(item)

    @operation()
    async def octop_skill_list(target_agent_id: str = "") -> dict[str, Any]:
        """List your expert's current skills, including enabled state and source."""
        row = expert(target_agent_id)
        return {
            "agent_id": row.agent_id,
            "skills": await manager.list_skill_summaries(row.agent_id),
        }

    @operation()
    async def octop_skill_search(query: str, limit: int = 10) -> dict[str, Any]:
        """Search SkillHub over HTTP; does not install skills or host software."""
        guard()
        if not 1 <= limit <= 50:
            raise ValueError("limit must be between 1 and 50")
        try:
            return {"skills": await search_skillhub(query, limit=limit)}
        except Exception as exc:
            raise ValueError(f"SkillHub search failed ({type(exc).__name__})") from None

    async def save_package(
        row: Any, package: Any, *, overwrite: bool, enabled: bool
    ) -> dict[str, Any]:
        try:
            await commit_skill_install(
                AgentWorkspaceSkillTarget(manager, row.agent_id, identity(writes=True)),
                package,
                overwrite=overwrite,
                enable=enabled,
            )
        except SkillAlreadyExistsError:
            raise ValueError(
                "skill already exists; overwrite requires an explicit request"
            ) from None
        return receipt(row.agent_id, slug=package.slug, enabled=enabled)

    @operation(writes=True)
    async def octop_skill_install(
        skill_slug: str = "",
        url: str = "",
        enabled: bool = True,
        overwrite: bool = False,
        target_agent_id: str = "",
    ) -> dict[str, Any]:
        """Install one SkillHub slug OR a supported skill bundle URL into your expert.

        Validates paths, size and manifest before writing. Does not execute package
        scripts or install their dependencies. Existing skills require overwrite=true.
        Skills become readable at the next model request; conversation skill filters remain.
        """
        row = expert(target_agent_id, writes=True)
        if bool(skill_slug) == bool(url):
            raise ValueError("provide exactly one SkillHub slug or URL")
        try:
            package = (
                await asyncio.to_thread(resolve_url_import, bundle_url=url)
                if url
                else prepare_skillhub_package(
                    validate_skill_slug(skill_slug), await download_skillhub_package(skill_slug)
                )
            )
            # URL imports share archive validation, then require a runtime-readable manifest.
            package = prepare_skillhub_package(package.slug, list(package.files))
        except Exception as exc:
            raise ValueError(f"skill download/validation failed ({type(exc).__name__})") from None
        return await save_package(row, package, overwrite=overwrite, enabled=enabled)

    @operation(writes=True)
    async def octop_skill_save(
        slug: str,
        content: str,
        files: dict[str, str] | None = None,
        enabled: bool = True,
        overwrite: bool = False,
        target_agent_id: str = "",
    ) -> dict[str, Any]:
        """Create or explicitly replace your workspace skill and optional UTF-8 support files.

        content must be SKILL.md with YAML name/description. files maps safe relative
        paths to text; it cannot replace SKILL.md. Mounted/builtin/locked skills stay
        protected. Saving files does not execute scripts or install dependencies.
        """
        row = expert(target_agent_id, writes=True)
        if files and "SKILL.md" in files:
            raise ValueError("provide the manifest in content only")
        package = prepare_skillhub_package(
            slug,
            [
                ("SKILL.md", content.encode("utf-8")),
                *((path, data.encode("utf-8")) for path, data in (files or {}).items()),
            ],
        )
        return await save_package(row, package, overwrite=overwrite, enabled=enabled)

    @operation(writes=True)
    async def octop_skill_set_enabled(
        slug: str, enabled: bool, target_agent_id: str = ""
    ) -> dict[str, Any]:
        """Enable/disable an installed skill for your expert without reloading its graph."""
        from octop_harness.skills.catalog import skill_identity_keys

        row = expert(target_agent_id, writes=True)
        validate_skill_slug(slug)
        summaries = await manager.list_skill_summaries(row.agent_id)
        item = next((item for item in summaries if item.get("slug") == slug), None)
        if item is None:
            raise ValueError("installed skill not found")
        keys = skill_identity_keys(item)
        disabled = set(manager.get_config(row.agent_id).get("skills_disabled") or [])
        await manager.persist_skills_disabled(
            row.agent_id, disabled - keys if enabled else disabled | keys
        )
        return receipt(row.agent_id, slug=slug, enabled=enabled)

    @operation()
    async def octop_plugin_catalog() -> dict[str, Any]:
        """Discover installed and marketplace plugins that extend tools/skills/middleware.

        Plugin installation is server-wide and can execute plugin code/dependency
        installation. It requires the plugins module permission, not a fixed admin role.
        Use MCP for external tool services and skills for workspace instructions.
        """
        user = guard()
        mgr = plugin_manager()
        return {
            "installed": mgr.list_installed(),
            "market": mgr.list_market(),
            "can_install": user.role == "admin" or "plugins" in user.permissions,
        }

    @operation(writes=True)
    async def octop_plugin_install(
        plugin_id: str = "", url: str = "", overwrite: bool = False
    ) -> dict[str, Any]:
        """Install an explicitly requested server-wide plugin by market id OR package URL.

        Requires plugins management permission. May execute package code/dependencies,
        just like Dashboard installation. Does not grant account/device permissions.
        Active turns are never restarted: new plugin tools/middleware load after them.
        """
        guard(writes=True, module="plugins")
        expert(writes=True)
        if bool(plugin_id) == bool(url):
            raise ValueError("provide exactly one marketplace plugin_id or URL")
        mgr = plugin_manager()
        try:
            loaded = (
                await asyncio.to_thread(mgr.install_url, url, force=overwrite)
                if url
                else await asyncio.to_thread(mgr.install_from_market, plugin_id, force=overwrite)
            )
        except OctopError:
            raise
        except Exception as exc:
            raise ValueError(f"plugin installation failed ({type(exc).__name__})") from None
        # Installation registers the plugin. Queue reloads; never close an active graph.
        for row in repos.agent_repo.list_all():
            manager.schedule_reload(row.agent_id)
        return {
            "agent_id": agent_id,
            "saved": True,
            "plugin_id": loaded.manifest.id,
            "version": loaded.manifest.version,
            "effective": "after_current_turn",
            "reload_status": "scheduled_after_active_turns",
        }

    @operation(writes=True)
    async def octop_plugin_set_enabled(
        plugin_id: str, enabled: bool, target_agent_id: str = ""
    ) -> dict[str, Any]:
        """Set your expert's plugin switch, preserving all other plugins and tool settings."""
        row = expert(target_agent_id, writes=True)
        installed_plugin(plugin_id)
        merged = merge_plugins_enabled_settings(
            manager.get_config(row.agent_id).get("plugins"), {plugin_id: enabled}
        )
        await manager.persist_plugin_tools_config(row.agent_id, merged)
        return receipt(row.agent_id, reload=True, plugin_id=plugin_id, enabled=enabled)

    @operation()
    async def octop_tool_list(target_agent_id: str = "") -> dict[str, Any]:
        """Discover builtin and installed plugin tool switches. New tools come from plugins/MCP."""
        row = expert(target_agent_id)
        cfg = manager.get_config(row.agent_id)
        disabled = set(cfg.get("tools_disabled") or [])
        plugins = []
        if manager._plugin_manager is not None:
            for plugin in plugin_manager().list_installed():
                if plugin.get("error"):
                    continue
                entry = (cfg.get("plugins") or {}).get(plugin["id"]) or {}
                for tool in plugin.get("tools") or []:
                    plugins.append(
                        {
                            "name": tool["name"],
                            "plugin_id": plugin["id"],
                            "enabled": (entry.get("tools") or {})
                            .get(tool["name"], {})
                            .get("enabled", True),
                            "available": plugin.get("enabled", True)
                            and agent_plugin_enabled(cfg.get("plugins"), plugin["id"]),
                        }
                    )
        return {
            "agent_id": row.agent_id,
            "builtin": [
                {
                    "name": entry.name,
                    "enabled": entry.name not in disabled,
                    "disableable": entry.name not in CRITICAL_TOOLS,
                    "available": builtin_tool_available(
                        entry.name,
                        agent_cfg=cfg,
                        mobile_enabled=bool(manager._config.capabilities.mobile.enabled),
                    ),
                }
                for entry in BUILTIN_TOOL_CATALOG
            ],
            "plugin_tools": plugins,
            "extend_with": ["octop_plugin_install", "octop_mcp_upsert", "octop_skill_save"],
        }

    @operation(writes=True)
    async def octop_tool_set_enabled(
        name: str, enabled: bool, plugin_id: str = "", target_agent_id: str = ""
    ) -> dict[str, Any]:
        """Toggle a builtin or plugin tool for your expert; other switches are preserved.

        Use the original plugin tool name from octop_tool_list with plugin_id.
        Critical tools cannot be disabled. Removed tools stop immediately; enabling
        graph-bound tools may wait for the current turn to finish.
        """
        row = expert(target_agent_id, writes=True)
        cfg = manager.get_config(row.agent_id)
        if plugin_id:
            plugin = installed_plugin(plugin_id)
            if name not in {tool["name"] for tool in plugin.get("tools") or []}:
                raise ValueError("plugin tool not found")
            merged = merge_plugins_tool_settings(
                cfg.get("plugins"), {plugin_id: {"tools": {name: {"enabled": enabled}}}}
            )
            await manager.persist_plugin_tools_config(row.agent_id, merged)
        else:
            if name not in {entry.name for entry in BUILTIN_TOOL_CATALOG} or (
                not enabled and name in CRITICAL_TOOLS
            ):
                raise ValueError("unknown or critical tool cannot be disabled")
            if name == "acp_runner":
                section = dict(cfg.get("acp") or {})
                section["tool_enabled"] = enabled
                cfg["acp"] = section
                await manager.update_config_json(row.agent_id, json.dumps(cfg))
            disabled = set(cfg.get("tools_disabled") or [])
            await manager.persist_tools_disabled(
                row.agent_id, disabled - {name} if enabled else disabled | {name}
            )
        return receipt(row.agent_id, reload=enabled, tool_name=name, enabled=enabled)

    @operation()
    async def octop_mcp_list() -> dict[str, Any]:
        """List your custom MCP servers without stored headers, environment, URLs or tokens."""
        user = guard()
        return {
            "servers": [
                {
                    "name": name,
                    "instance_id": f"custom:{name}",
                    "transport": spec.get("transport"),
                    "display_name": spec.get("display_name", name),
                    "enabled": spec.get("enabled", True),
                    "default_open": spec.get("default_open", False),
                }
                for name, spec in manager._connector_svc.get_custom_servers(user.id).items()
            ],
            "configure_with": "octop_mcp_upsert",
            "attach_with": "octop_connector_attach",
            "transports": {
                "streamable_http": ["url", "headers (optional)"],
                "stdio": ["command", "args (optional)", "env (optional)"],
            },
        }

    @operation(writes=True)
    async def octop_mcp_upsert(
        name: str, server: dict[str, Any], overwrite: bool = False
    ) -> dict[str, Any]:
        """Create/merge your custom MCP server using existing validated encrypted storage.

        server.transport is streamable_http (url/headers) or stdio (command/args/env).
        stdio runs on the application server, not the selected device. Only configure
        a server the user requested. Requires connectors permission. New servers are
        private and not default-open. Existing names require explicit overwrite=true;
        omitted settings/secrets and all other servers are preserved. Attach its
        returned instance_id with octop_connector_attach; test before claiming it works.
        A different target must use a new name when saved authentication exists.
        OAuth grants are obtained through the provider consent flow, not this tool.
        """
        user = guard(writes=True, module="connectors")
        svc = manager._connector_svc
        servers = svc.get_custom_servers(user.id)
        if name in servers and not overwrite:
            raise ValueError("MCP server already exists; overwrite requires an explicit request")
        previous = servers.get(name) or {}
        if "oauth" in server:
            raise ValueError(
                "use the provider consent flow for OAuth, or explicitly supplied headers for token authentication"
            )
        merged = {**previous, **server}
        if merged.get("transport") == "http":
            merged["transport"] = "streamable_http"
        changed_target = any(
            merged.get(key) != previous.get(key) for key in ("transport", "url", "command")
        )
        if (
            previous
            and changed_target
            and any(previous.get(key) for key in ("headers", "env", "oauth", "args"))
        ):
            raise ValueError(
                "use a new MCP server name for a different target; saved authentication cannot be forwarded automatically"
            )
        if "transport" in server and merged["transport"] != previous.get("transport"):
            merged = {
                key: value
                for key, value in merged.items()
                if key not in {"headers", "env", "oauth", "args", "url", "command"} or key in server
            }
        servers[name] = merged
        svc.put_custom_servers(user.id, servers)
        return receipt(
            agent_id,
            instance_id=f"custom:{name}",
            mcp_server_name=name,
            authentication_verified=False,
            effective="saved_not_attached",
        )

    @operation(writes=True)
    async def octop_mcp_test(name: str) -> dict[str, Any]:
        """Connect to your saved MCP server and discover tools without calling those tools.

        stdio starts the configured server process. OAuth may still require consent
        through Dashboard. Probe failures must not be described as successful login.
        Stored credentials and connection arguments are redacted from results.
        """
        user = guard(writes=True, module="connectors")
        svc = manager._connector_svc
        spec = svc.get_custom_servers(user.id).get(name)
        if not isinstance(spec, dict) or not spec.get("enabled", True):
            raise ValueError("enabled owned MCP server required")
        try:
            result = await probe_custom_mcp_server(spec)
        except Exception as exc:
            result = {"ok": False, "error": str(exc)}
        if (result.get("oauth") or {}).get("available"):
            from octop.infra.connectors.custom_mcp import oauth_configured

            if not oauth_configured(spec):
                svc.note_custom_server_oauth_required(user.id, name, required=True)
        return {"agent_id": agent_id, "name": name, **redact_mcp_result(result, spec)}
