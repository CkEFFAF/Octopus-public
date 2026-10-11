"""Process-local workspaces usable both by the dashboard and graph execution.

deepagents StateBackend requires a running graph. Octop also needs workspace I/O
when seeding templates and receiving attachments before a graph starts. Reuse its
StoreBackend with an explicit in-memory store, isolated per agent and route.
"""

from __future__ import annotations

from typing import Any

from deepagents.backends.store import StoreBackend
from langgraph.store.memory import InMemoryStore


def has_ephemeral_workspace(spec: Any) -> bool:
    if spec == "state":
        return True
    if not isinstance(spec, dict):
        return False
    if spec.get("type") == "state":
        return True
    if spec.get("type") == "composite":
        return has_ephemeral_workspace(spec.get("default")) or any(
            has_ephemeral_workspace(value) for value in (spec.get("routes") or {}).values()
        )
    return False


class EphemeralWorkspaces:
    def __init__(self) -> None:
        self._backends: dict[tuple[str, tuple[str, ...]], StoreBackend] = {}

    def resolve(self, agent_id: str, spec: Any, route: tuple[str, ...] = ()) -> Any:
        if spec == "state" or isinstance(spec, dict) and spec.get("type") == "state":
            key = (agent_id, route)
            if key not in self._backends:
                self._backends[key] = MemoryWorkspaceBackend(
                    store=InMemoryStore(), namespace=lambda _runtime: ("workspace",)
                )
            return self._backends[key]
        if isinstance(spec, dict) and spec.get("type") == "composite":
            return {
                **spec,
                "default": self.resolve(agent_id, spec["default"], (*route, "default")),
                "routes": {
                    prefix: self.resolve(agent_id, value, (*route, prefix))
                    for prefix, value in (spec.get("routes") or {}).items()
                },
            }
        return spec

    def discard(self, agent_id: str) -> None:
        for key in list(self._backends):
            if key[0] == agent_id:
                del self._backends[key]


class MemoryWorkspaceBackend(StoreBackend):
    def mkdir_path(self, path: str) -> None:
        """Store directories are implicit prefixes created by uploaded files."""
