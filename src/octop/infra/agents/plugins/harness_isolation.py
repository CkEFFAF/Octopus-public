"""Fail closed for harness plugin model contexts shared across account-owned agents.

Harness 1.0.1/1.0.2 binds every global PluginContext to the most recently
constructed agent. Until harness exposes an account-scoped context, those
contexts must never hold a real account's factory or protocol resolver.
"""

from __future__ import annotations

import logging
from typing import Any

from octop_harness import HarnessAgentManager
from octop_harness.plugins.context import PluginContext
from octop_harness.plugins.registry import PluginRegistry
from octop_harness.registry import AgentEntry

logger = logging.getLogger(__name__)
_DENIED_MESSAGE = (
    "Shared plugin model access is disabled: octop-harness requires an "
    "account-scoped plugin context before provider credentials can be exposed."
)


class _DeniedPluginFactory:
    def __getattr__(self, name: str) -> Any:
        raise RuntimeError(_DENIED_MESSAGE)


def _seal_plugin_model_contexts() -> None:
    for loaded in PluginRegistry().all_loaded():
        ctx = loaded.context
        if not isinstance(ctx, PluginContext) or isinstance(
            ctx.model_factory, _DeniedPluginFactory
        ):
            continue
        denied = _DeniedPluginFactory()
        ctx.bind_model_factory(denied, get_protocol=None)

        # Instance-local replacement prevents later harness constructors from
        # assigning another owner's factory. No turn-time global rebinding.
        def refuse_bind(factory: Any, *, get_protocol: Any | None = None) -> None:
            return None

        ctx.bind_model_factory = refuse_bind  # type: ignore[method-assign]
        logger.warning("Plugin %s: %s", loaded.manifest.id, _DENIED_MESSAGE)


class AccountIsolatedHarnessManager(HarnessAgentManager):
    """Guard initial creation and internal MCP/security rebuild registrations."""

    def _register_agent(
        self,
        config: Any,
        *,
        metadata: dict[str, Any] | None = None,
        tags: list[str] | None = None,
        agent_id: str,
        init_workspace: bool = True,
    ) -> AgentEntry:
        # Empty per-agent providers trigger harness's hub-environment fallback.
        # Recheck at registration after lifecycle locks, including internal rebuilds.
        if not config.providers:
            raise ValueError("No usable account-owned provider configured for this agent")
        _seal_plugin_model_contexts()
        return super()._register_agent(
            config,
            metadata=metadata,
            tags=tags,
            agent_id=agent_id,
            init_workspace=init_workspace,
        )
