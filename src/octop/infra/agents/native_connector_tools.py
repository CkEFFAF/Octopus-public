"""Account-scoped connector configuration exposed through native product tools."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from langgraph.config import get_config

from octop.infra.agents.middleware.live_configuration import (
    LiveConfigurationMiddleware,
    remember_self_update,
)
from octop.infra.agents.native_tool_types import NativeOperation
from octop.infra.agents.settings.profile import id_list_from_row
from octop.infra.connectors.catalog import catalog_entry_to_dict, get_catalog_entry, list_catalog
from octop.infra.connectors.default_open import read_default_open
from octop.infra.connectors.gateway.cli_install import get_cli_install_spec
from octop.infra.connectors.service import ConnectorService
from octop.infra.errors import ErrorCode, OctopError


def connector_fields(kind: str) -> list[dict[str, Any]]:
    entry = get_catalog_entry(kind)
    if entry is None:
        raise ValueError("unknown connector kind")
    fields: list[dict[str, Any]] = []

    def add(key: str, *, secret: bool = False, required: bool = True, **extra: Any) -> None:
        fields.append({"key": key, "secret": secret, "required": required, **extra})

    if entry.auth_kind == "imap_app_password":
        add("email")
        add(
            "password",
            secret=True,
            help="Mailbox authorization/app password explicitly supplied by the user.",
        )
        add("mail_provider", required=False, choices=["qq", "netease", "gmail", "custom"])
        add(
            "imap_host",
            required=False,
            help="Required for custom/university mailboxes. Use the provider's IMAP TLS host.",
        )
        add("imap_port", required=False, default=993)
        add("smtp_host", required=False, help="Required for custom/university mailboxes.")
        add(
            "smtp_port",
            required=False,
            default=587,
            help="465 uses implicit TLS; other ports use STARTTLS.",
        )
    elif entry.auth_kind == "personal_token":
        add("token", secret=True)
    elif entry.auth_kind == "api_key":
        if kind == "feishu-cli":
            add("app_id")
            add("app_secret", secret=True)
            add("default_as", required=False, choices=["bot", "user"])
        elif kind == "wecom-cli":
            add("bot_id")
            add("bot_secret", secret=True)
        else:
            add("api_key", secret=True)
            if kind in {"tencent-ima", "tencent-lexiang"}:
                add("client_id")
    elif entry.auth_kind == "oauth2":
        add("access_token", secret=True, required=False)
        add("refresh_token", secret=True, required=False)
        add("oauth_client_id", required=False)
        add("oauth_client_secret", secret=True, required=False)
        if kind == "qcc":
            add("api_key", secret=True, required=False, help="Alternative to an OAuth grant.")
    elif entry.auth_kind == "auth_code":
        add("code", secret=True)
        add("bkn", required=False)
        add("knowledge_base_id", required=False)
    elif entry.auth_kind == "session_cookie":
        add("cookie", secret=True)
    elif entry.auth_kind == "api_credentials":
        add("app_id")
        add("sdk_id")
        add("secret_key", secret=True)
    else:
        for field in entry.credential_fields:
            add(field.key, secret=field.secret, required=field.required, help=field.help)
    return fields


def register_connector_tools(
    manager: Any,
    repos: Any,
    agent_id: str,
    *,
    identity: Callable[..., Any],
    owned: Callable[..., Any],
    operation: NativeOperation,
) -> None:
    def service(*, writes: bool = False) -> ConnectorService:
        user = identity(writes=writes)
        cfg = get_config().get("configurable") or {}
        if cfg.get("octop_shared_text_scope") is not None:
            raise OctopError(
                ErrorCode.FORBIDDEN,
                "connector management is unavailable in foreign shared-text collaboration",
            )
        if writes and user.role != "admin" and "connectors" not in user.permissions:
            raise OctopError(
                ErrorCode.FORBIDDEN,
                "connectors management permission required; administrator role is not required",
            )
        svc: ConnectorService = manager._connector_svc
        return svc

    def payload(row: Any) -> dict[str, Any]:
        config = repos.connector_repo.parse_config_json(row)
        return {
            "instance_id": row.instance_id,
            "kind": row.kind,
            "display_name": row.display_name,
            "description": config.get("description"),
            "status": row.status,
            "mcp_server_name": row.mcp_server_name,
            "has_credentials": row.has_credentials,
            "shared": row.shared,
            "default_open": read_default_open(config),
            "owner_user_id": row.user_id,
            "writable": row.user_id == identity().id,
        }

    @operation()
    async def octop_connector_catalog(kind: str = "") -> dict[str, Any]:
        """Discover connector kinds and exact configuration fields before creating one.

        Personal/university mailboxes use qq-mail with mail_provider=custom and
        explicit IMAP/SMTP hosts/ports, not Agently Mail. Configuration does not
        require a Dashboard administrator. OAuth may require the user's consent;
        never borrow host/CLI login tokens or install software to obtain it.
        """
        service()
        entries = [entry for entry in list_catalog() if not kind or entry.kind == kind]
        if not entries:
            raise ValueError("unknown connector kind")
        user = identity()
        return {
            "can_manage": user.role == "admin" or "connectors" in user.permissions,
            "catalog": [
                {
                    **catalog_entry_to_dict(entry),
                    "credential_fields": connector_fields(entry.kind),
                    "requires_host_cli": get_cli_install_spec(entry.kind) is not None,
                }
                for entry in entries
            ],
            "rules": "Use only credentials explicitly supplied for this connection. They are encrypted at rest but tool inputs remain conversation data. Do not guess university mail servers. OAuth consent and missing host software are separate from mailbox configuration. Test before claiming authentication works; attach with octop_connector_attach. Interactive authorization is available at /connectors.",
        }

    @operation()
    async def octop_connector_list() -> dict[str, Any]:
        """List your connections and visible shared connections without credentials."""
        service()
        return {
            "instances": [payload(row) for row in repos.connector_repo.list_visible(identity().id)]
        }

    @operation()
    async def octop_connector_get(instance_id: str) -> dict[str, Any]:
        """Inspect your connection's settings and configured-secret flags, never saved secrets."""
        svc = service()
        row = svc.owned_instance(identity().id, instance_id)
        credentials = svc.decrypt(instance_id)
        safe = {
            key: credentials[key]
            for key in (
                "email",
                "mail_provider",
                "imap_host",
                "imap_port",
                "smtp_host",
                "smtp_port",
            )
            if key in credentials
        }
        fields = connector_fields(row.kind)
        return {
            **payload(row),
            "settings": safe,
            "credential_fields": fields,
            "configured_secret_fields": [
                field["key"]
                for field in fields
                if field["secret"] and credentials.get(field["key"])
            ],
        }

    @operation(writes=True)
    async def octop_connector_create(
        kind: str,
        display_name: str,
        credentials: dict[str, Any],
        description: str | None = None,
    ) -> dict[str, Any]:
        """Create your private connection with explicitly provided credentials, encrypted at rest.

        Discover fields first. No admin role or CLI login is needed. Saving does
        not prove authentication; test it, then use octop_connector_attach to
        enable it for the current expert/conversation. Never echo passwords.
        """
        svc = service(writes=True)
        row = await svc.create_instance(
            identity().id,
            kind=kind,
            display_name=display_name,
            credentials=credentials,
            description=description,
        )
        return {
            **payload(row),
            "agent_id": agent_id,
            "saved": True,
            "authentication_verified": False,
        }

    @operation(writes=True)
    async def octop_connector_update(
        instance_id: str,
        display_name: str | None = None,
        description: str | None = None,
        credentials: dict[str, Any] | None = None,
        status: str | None = None,
        default_open: bool | None = None,
    ) -> dict[str, Any]:
        """Edit your connection or rotate its credentials; omitted fields stay unchanged.

        status is active/disabled. default_open changes account-wide defaults
        only when explicitly requested. Shared connections owned by others cannot
        be edited. Credentials are never returned. Test again after rotation.
        """
        svc = service(writes=True)
        row = await svc.update_instance(
            identity().id,
            instance_id,
            display_name=display_name,
            description=description,
            credentials=credentials,
            status=status,
            default_open=default_open,
        )
        return {
            **payload(row),
            "agent_id": agent_id,
            "saved": True,
            "authentication_verified": False,
        }

    @operation(writes=True)
    async def octop_connector_test(instance_id: str) -> dict[str, Any]:
        """Test your saved connection's login/capabilities without sending mail or messages.

        Uses vault credentials internally, never returns them. A failed test
        must not be described as connected. A mailbox test checks IMAP login;
        it does not send a test email or verify SMTP delivery.
        """
        svc = service(writes=True)
        result = await svc.probe_instance(identity().id, instance_id, locale=identity().locale)
        return {"instance_id": instance_id, "agent_id": agent_id, **result}

    @operation(writes=True)
    async def octop_connector_attach(instance_id: str, target_agent_id: str = "") -> dict[str, Any]:
        """Add a visible active connection to your expert, preserving other selections.

        The current conversation receives its tools at the next model request.
        No active graph is restarted. Does not claim upstream login was tested.
        """
        service(writes=True)
        row = owned(target_agent_id, kind="expert")
        connection = next(
            (
                item
                for item in service().list_instances_for_api(identity().id)
                if item["instance_id"] == instance_id
            ),
            None,
        )
        if (
            connection is None
            or connection["status"] != "active"
            or not connection["has_credentials"]
        ):
            raise OctopError(ErrorCode.FORBIDDEN, "visible active configured connector required")
        cfg = get_config().get("configurable") or {}
        names = (
            LiveConfigurationMiddleware(manager, row.agent_id).resolve_selection(cfg)
            if row.agent_id == agent_id
            else id_list_from_row(row, "mcp_servers")
        )
        names = list(dict.fromkeys([*names, connection["mcp_server_name"]]))
        if row.agent_id == agent_id:
            allowed = LiveConfigurationMiddleware(manager, row.agent_id).resolve_selection(
                cfg, explicit=names
            )
            if connection["mcp_server_name"] not in allowed:
                raise OctopError(
                    ErrorCode.FORBIDDEN, "connector denied by this conversation or device policy"
                )
        names = manager.validate_mcp_servers(identity().id, names)
        from octop.infra.agents.settings.profile import dump_id_list

        await manager.update(row.agent_id, mcp_servers=dump_id_list(names))
        applied = remember_self_update(manager, row.agent_id, names)
        return {
            "instance_id": instance_id,
            "agent_id": row.agent_id,
            "saved": True,
            "current_conversation_update": {"mcp_servers": names, "effective": "next_model_request"}
            if applied
            else None,
            "mcp_servers": names,
            "reload_status": "not_required",
        }
