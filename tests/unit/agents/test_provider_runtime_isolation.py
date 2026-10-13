"""Equal public refs resolve to separate owner credentials and runtime caches."""

import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from octop_harness.plugins.context import PluginContext, register_loaded
from octop_harness.plugins.manifest import PluginManifest
from octop_harness.plugins.registry import PluginRegistry

from octop.config import OctopConfig
from octop.infra.agents.manager import AgentManager
from octop.infra.agents.plugins.harness_isolation import (
    AccountIsolatedHarnessManager as HarnessAgentManager,
)
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import build_shared_services
from octop.infra.utils.paths import PathLayout


def _registry(tmp_path: Path) -> AgentManager:
    paths = PathLayout(tmp_path)
    db = SqlitePool(paths.db)
    run_migrations(db)
    services = build_shared_services(db=db, paths=paths, config=OctopConfig())
    for username, key in (("a", "secret-a"), ("b", "secret-b")):
        uid = services.user_repo.create(username=username, password_hash="hash", role="user")
        services.provider_repo.create(
            user_id=uid,
            name="same",
            kind="openai",
            base_url="https://example.test/v1",
            api_key=key,
            models_json=json.dumps([{"id": "gpt-4o-mini", "enabled": True}]),
        )
        services.agent_repo.create(
            agent_id=username,
            user_id=uid,
            name=username,
            config_json=json.dumps({"memory": {"memory_enabled": False}}),
        )
        services.agent_repo.set_shared(username, username == "a")
    return AgentManager(repos=services.repos, paths=paths)


@pytest.mark.asyncio
async def test_actual_agents_use_owner_factories_without_shared_cache(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    hm = HarnessAgentManager(providers=[], log_dir=str(registry.paths.logs_dir))
    registry._harness_manager = hm
    try:
        a = registry._repos.agent_repo.get("a")
        b = registry._repos.agent_repo.get("b")
        first = await hm.acreate_agent(
            registry._build_harness_config(a), agent_id="a", init_workspace=False
        )
        second = await hm.acreate_agent(
            registry._build_harness_config(b), agent_id="b", init_workspace=False
        )
        assert hm.shared_factory is None
        a_factory, b_factory = first.agent.model_factory, second.agent.model_factory
        assert a_factory is not b_factory
        assert a_factory.provider_configs()[0].api_key == "secret-a"
        assert b_factory.provider_configs()[0].api_key == "secret-b"
        a_model = a_factory.get("same/gpt-4o-mini")
        b_model = b_factory.get("same/gpt-4o-mini")
        assert a_model.chat_model is not b_model.chat_model
        assert a_factory.get("same/gpt-4o-mini").chat_model is a_model.chat_model
        assert b_factory.get("same/gpt-4o-mini").chat_model is b_model.chat_model
        registry._reload_agents = AsyncMock()
        await registry.on_provider_changed(user_id=a.user_id, active_model_changed=True)
        assert registry._reload_agents.await_args.args == (["a"],)
        assert b_factory.get("same/gpt-4o-mini").chat_model is b_model.chat_model
    finally:
        await hm.aclose()


@pytest.mark.asyncio
async def test_shared_plugin_cannot_acquire_either_accounts_model_factory(tmp_path: Path) -> None:
    registry = _registry(tmp_path)
    plugin_registry = PluginRegistry()
    plugin = PluginContext(
        manifest=PluginManifest(
            id="account-isolation-test", version="1", name="Test", kind="tool", entry="main.py"
        ),
        source_path=tmp_path,
    )
    plugin.tool("ordinary_tool", lambda: "works without model access")
    register_loaded(plugin)
    hm = HarnessAgentManager(providers=[], log_dir=str(registry.paths.logs_dir))
    try:
        for aid in ("a", "b"):
            row = registry._repos.agent_repo.get(aid)
            entry = await hm.acreate_agent(
                registry._build_harness_config(row), agent_id=aid, init_workspace=False
            )
            assert plugin.model_factory is not entry.agent.model_factory
            assert plugin.get_protocol is None
            with pytest.raises(RuntimeError, match="account-scoped plugin context"):
                plugin.get_model_access("same/gpt-4o-mini")
        loaded = plugin_registry.get("account-isolation-test")
        assert loaded.tools[0].fn() == "works without model access"
        with pytest.raises(RuntimeError, match="account-scoped plugin context"):
            plugin.model_factory.provider_configs()
    finally:
        await hm.aclose()
        plugin_registry.unregister("account-isolation-test")


@pytest.mark.asyncio
async def test_ownerless_legacy_agent_fails_closed_even_with_other_account_providers(
    tmp_path: Path,
) -> None:
    registry = _registry(tmp_path)
    registry._repos.agent_repo.create(agent_id="legacy", user_id=None, name="legacy")
    row = registry._repos.agent_repo.get("legacy")
    hm = HarnessAgentManager(providers=[], log_dir=str(registry.paths.logs_dir))
    registry._harness_manager = hm
    try:
        assert await registry._start_agent(row) is None
        assert registry._repos.agent_repo.get("legacy").last_state == "failed"
        assert registry.providers_for_agent("legacy").build_harness_configs() == []
    finally:
        await hm.aclose()


@pytest.mark.asyncio
async def test_provider_removed_while_start_waits_cannot_fall_back_to_hub_credentials(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path)
    monkeypatch.setenv("OPENAI_API_KEY", "hub-secret-never-use")
    hm = HarnessAgentManager(providers=[], log_dir=str(registry.paths.logs_dir))
    registry._harness_manager = hm
    row = registry._repos.agent_repo.get("a")
    lock = registry._lifecycle_lock_for("a")
    await lock.acquire()
    pending = asyncio.create_task(registry._start_agent(row, init_workspace=False))
    try:
        await asyncio.sleep(0)  # Startup passed its initial check and now waits for the lock.
        assert not pending.done()
        provider = registry._repos.provider_repo.get_by_name(row.user_id, "same")
        registry._repos.provider_repo.delete(row.user_id, provider.id)
        lock.release()
        assert await pending is None
        assert registry._repos.agent_repo.get("a").last_state == "failed"
        with pytest.raises(KeyError):
            hm.get_agent("a")
        # Internal rebuild registrations must enforce the same boundary.
        with pytest.raises(ValueError, match="account-owned provider"):
            hm._register_agent(registry._build_harness_config(row), agent_id="a")
    finally:
        if lock.locked():
            lock.release()
        await pending
        await hm.aclose()
