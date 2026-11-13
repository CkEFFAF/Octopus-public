from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from octop.infra.agents.providers.routing import (
    ModelRoutingConfig,
    ModelRoutingService,
    classify_model_task,
)
from octop.infra.agents.providers.store import ProviderStore
from octop.infra.agents.response_recovery import recovery_request
from octop.infra.conversations.service import ConversationService
from octop.infra.db.migrate import run_migrations
from octop.infra.db.pool import SqlitePool
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError


@pytest.fixture
def routing(tmp_path):
    pool = SqlitePool(tmp_path / "routing.db")
    run_migrations(pool)
    repos = RepoBundle.from_pool(pool)
    owner = repos.user_repo.create(username="owner", password_hash="h", role="user")
    other = repos.user_repo.create(username="other", password_hash="h", role="user")
    models = [
        {"id": "plain", "input": ["text"], "context_window": 64000},
        {"id": "coder-lite", "input": ["text"], "context_window": 64000},
        {"id": "image", "input": ["text", "image"], "context_window": 128000},
        {"id": "large", "input": ["text"], "context_window": 1000000},
        {"id": "embed", "embedding": True, "input": ["text"]},
    ]
    provider = repos.provider_repo.create(
        user_id=owner,
        name="Owned",
        kind="openai",
        base_url="https://example.invalid/v1",
        api_key="test",
        models_json=json.dumps(models),
    )
    repos.provider_repo.create(
        user_id=other,
        name="Other",
        kind="openai",
        base_url="https://other.invalid/v1",
        api_key="other-test",
        models_json=json.dumps([{"id": "secret-coder", "input": ["text"]}]),
    )
    repos.settings_repo.set_active_model(owner, "Owned", "plain")
    yield ModelRoutingService(repos, owner), repos, owner, other, provider, models
    pool.close()


@pytest.mark.parametrize(
    "text,mode,images,tokens,expected",
    [
        ("修复 Python 报错", None, False, 0, "coding"),
        ("查找相关文献", None, False, 0, "research"),
        ("证明这个数学结论", None, False, 0, "reasoning"),
        ("你好", None, True, 0, "vision"),
        ("看看历史", None, False, 50000, "long_context"),
        ("继续", "deep_research", False, 0, "research"),
        ("继续", "debug", False, 0, "coding"),
        ("分析 Python 脚本的实验结果，评估创新潜力", None, False, 0, "reasoning"),
        ("先做核心部分设计，再写代码", None, False, 0, "reasoning"),
        ("设计实验方案并给出代码改动建议", None, False, 0, "reasoning"),
        ("Architect the Python service and evaluate tradeoffs", None, False, 0, "reasoning"),
        ("Analyze the experiment results from this SQL script", None, False, 0, "reasoning"),
        ("修改 Python 脚本并运行单元测试", None, False, 0, "coding"),
        ("修复 Python 报错", "plan", False, 0, "reasoning"),
        ("这个实验失败了，请分析代码原因并提出优化方案", None, False, 0, "reasoning"),
        ("需要做重要的决策，分析代码结构", None, False, 0, "reasoning"),
        ("Design a core component in Python", None, False, 0, "reasoning"),
        ("深入推理 Python 代码中优化器不收敛的数学原因", None, False, 0, "reasoning"),
        ("Write a training script", None, False, 0, "coding"),
        ("Implement this function", None, False, 0, "coding"),
        ("你好", None, False, 0, "chat"),
    ],
)
def test_task_classification_uses_current_input_and_explicit_mode(
    text, mode, images, tokens, expected
):
    assert (
        classify_model_task(text, work_mode=mode, has_images=images, context_tokens=tokens)
        == expected
    )


def test_routing_is_opt_in_and_manual_selection_has_highest_priority(routing):
    router, *_ = routing
    assert router.resolve(text="写 Python 代码").model == "Owned/plain"
    router.save(ModelRoutingConfig(enabled=True, tasks={"coding": "Owned/large"}))
    configured = router.resolve(text="写 Python 代码")
    assert configured.model == "Owned/large" and configured.source == "task"
    manual = router.resolve(text="写 Python 代码", explicit_model="Owned/plain")
    assert manual.model == "Owned/plain" and manual.source == "manual"


def test_experiment_analysis_uses_reasoning_preference_without_changing_coding(routing):
    router, *_ = routing
    router.save(
        ModelRoutingConfig(
            enabled=True, tasks={"coding": "Owned/coder-lite", "reasoning": "Owned/large"}
        )
    )
    analysis = router.resolve(text="分析 Python 代码产生的实验结果，评估下一步方案")
    assert (analysis.task, analysis.model, analysis.source) == ("reasoning", "Owned/large", "task")
    assert router.resolve(text="实现 Python 脚本并修复报错").model == "Owned/coder-lite"
    assert router.resolve(text="分析实验结果", explicit_model="Owned/plain").model == "Owned/plain"


def test_auto_capabilities_and_long_context_are_checked_without_external_calls(routing):
    router, *_ = routing
    router.save(ModelRoutingConfig(enabled=True))
    assert router.resolve(text="Python 代码").model == "Owned/coder-lite"
    vision = router.resolve(has_images=True)
    assert vision.model == "Owned/image" and vision.reason == "image_capability"
    assert router.resolve(context_tokens=500000).model == "Owned/large"
    assert router.resolve(text="普通聊天").model == "Owned/plain"


def test_invalid_foreign_embedding_and_vision_refs_are_rejected(routing):
    router, repos, owner, other, *_ = routing
    for task, ref in [
        ("coding", "Other/secret-coder"),
        ("chat", "Owned/embed"),
        ("vision", "Owned/plain"),
    ]:
        with pytest.raises(OctopError) as error:
            router.save(ModelRoutingConfig(enabled=True, tasks={task: ref}))
        assert error.value.code == ErrorCode.MODEL_ROUTING_INVALID_MODEL
    assert not router.config().enabled
    assert {item["value"] for item in router.models()} == {
        "Owned/plain",
        "Owned/coder-lite",
        "Owned/image",
        "Owned/large",
    }
    router.save(ModelRoutingConfig(enabled=True, tasks={"chat": "Owned/large"}))
    foreign = ModelRoutingService(repos, other)
    assert not foreign.config().enabled
    assert foreign.resolve().model == "Other/secret-coder"


def test_disabled_model_is_revalidated_and_configuration_is_preserved(routing):
    router, repos, owner, other, provider, models = routing
    router.save(ModelRoutingConfig(enabled=True, tasks={"coding": "Owned/coder-lite"}))
    models[1]["enabled"] = False
    repos.provider_repo.update(owner, provider, models_json=json.dumps(models))
    decision = router.resolve(text="Python 代码")
    assert decision.model == "Owned/plain"
    assert decision.reason == "unavailable_task_model"
    assert router.config().tasks["coding"] == "Owned/coder-lite"


def test_auxiliary_explicit_and_same_as_title_choices_remain_authoritative(routing):
    router, repos, owner, *_ = routing
    router.save(
        ModelRoutingConfig(
            enabled=True, tasks={"title": "Owned/coder-lite", "summary": "Owned/large"}
        )
    )
    manager = SimpleNamespace(
        _repos=repos, providers_for_user=lambda uid: ProviderStore(repos.provider_repo, uid)
    )
    service = ConversationService(manager)
    assert service.resolve_model(owner, "account") == "Owned/coder-lite"
    assert service.resolve_model(owner, "account", "account", "summary") == "Owned/large"
    assert service.resolve_model(owner, "same", "account", "summary") == "Owned/coder-lite"
    assert service.resolve_model(owner, "Owned/plain", "account", "summary") == "Owned/plain"


def test_recovery_keeps_the_frozen_routing_decision_without_reclassifying(routing):
    router, *_ = routing
    router.save(ModelRoutingConfig(enabled=True, tasks={"coding": "Owned/coder-lite"}))
    decision = router.resolve(text="修复 Python 代码")
    saved = recovery_request(
        {
            "model": decision.model,
            "thread_id": "t",
            "configurable": {"octop_model_route": decision.model_dump()},
            "messages": [{"role": "user", "content": "private text"}],
        }
    )
    router.save(ModelRoutingConfig(enabled=True, tasks={"coding": "Owned/large"}))
    assert saved["model"] == "Owned/coder-lite"
    assert saved["configurable"]["octop_model_route"] == decision.model_dump()
    assert saved["messages"] == []


def test_direct_task_admission_routes_work_items_cron_and_peer_requests(routing):
    from octop.infra.agents.manager import AgentManager

    router, repos, owner, *_ = routing
    router.save(ModelRoutingConfig(enabled=True, tasks={"coding": "Owned/large"}))
    manager = AgentManager.__new__(AgentManager)
    manager._repos = repos
    manager.providers_for_agent = lambda aid: ProviderStore(repos.provider_repo, owner)
    manager.get_row = lambda aid: SimpleNamespace(default_model=None)
    manager.get_config = lambda aid: {}
    manager.get_thread_model = lambda aid, tid: None
    original = {
        "thread_id": "background",
        "messages": [{"role": "user", "content": "修复 Python 报错"}],
        "source": "cron",
    }
    chosen = manager._route_stream_request("expert", original)
    assert chosen["model"] == "Owned/large"
    assert chosen["configurable"]["octop_model_route"]["source"] == "task"
    assert "model" not in original
    router.save(ModelRoutingConfig(enabled=True, tasks={"coding": "Owned/coder-lite"}))
    assert manager._route_stream_request("expert", chosen) == chosen
    manual = manager._route_stream_request("expert", {**original, "model": "Owned/plain"})
    assert manual["model"] == "Owned/plain"
    assert manual["configurable"]["octop_model_route"]["source"] == "manual"
    manager.get_thread_model = lambda aid, tid: "Owned/plain"
    assert manager._route_stream_request("expert", original)["model"] == "Owned/plain"
    shared = {**original, "configurable": {"octop_shared_text_scope": {}}}
    assert manager._route_stream_request("expert", shared) is shared


@pytest.mark.asyncio
async def test_embedded_acp_uses_managed_owner_stream(routing):
    from octop.infra.agents.acp import ManagedACPStream

    _, repos, owner, *_ = routing
    repos.agent_repo.create(agent_id="expert", user_id=owner, name="ACP expert")
    seen = []

    async def stream(agent_id, request):
        seen.append((agent_id, request))
        yield {"type": "model_route", "model": "Owned/coder"}
        yield {"type": "token", "content": "done"}

    manager = SimpleNamespace(
        _repos=repos, get_row=lambda aid: SimpleNamespace(user_id=owner), stream=stream
    )
    request = {
        "thread_id": "acp-session",
        "user": "other",
        "messages": [{"role": "user", "content": "Python"}],
    }
    chunks = [chunk async for chunk in ManagedACPStream(manager, "expert").stream(request)]
    assert seen == [("expert", {**request, "user": str(owner)})]
    assert repos.thread_repo.get("acp-session").user_id == owner
    assert request["user"] == "other"
    assert chunks[-1]["content"] == "done"


def test_gateway_uses_saved_execution_mode_before_freezing_route(routing):
    from octop.infra.db.repos.execution import ExecutionContextRepo
    from octop.infra.devices.service import DeviceService
    from octop.infra.gateway.process.processor import GlobalProcessor

    router, repos, owner, *_ = routing
    repos.agent_repo.create(agent_id="mode-expert", user_id=owner, name="Mode expert")
    repos.thread_repo.insert(
        thread_id="mode-thread",
        agent_id="mode-expert",
        user_id=owner,
        channel_type="ui",
        session_key="ui",
    )
    router.save(
        ModelRoutingConfig(
            enabled=True, tasks={"coding": "Owned/large", "research": "Owned/coder-lite"}
        )
    )
    ExecutionContextRepo(repos.db).save_selection(owner, "mode-thread", {"work_mode": "debug"})
    processor = GlobalProcessor.__new__(GlobalProcessor)
    processor._agent_manager = SimpleNamespace(
        _repos=repos,
        _device_service=DeviceService(repos),
        providers_for_agent=lambda aid: ProviderStore(repos.provider_repo, owner),
        get_thread_model=lambda aid, tid: None,
        get_config=lambda aid: {},
        resolve_fallback_model_ref=lambda uid: "Owned/plain",
    )
    processor._agent_repo = repos.agent_repo
    processor._user_repo = repos.user_repo
    processor._thread_registry = SimpleNamespace(get_thread=repos.thread_repo.get)
    info = {}
    selected = processor._resolve_harness_model(
        "mode-expert",
        "mode-thread",
        None,
        needs_multimodal=False,
        user_id=owner,
        text="继续",
        routing_info=info,
    )
    assert selected == "Owned/large"
    assert info["task"] == "coding"
    selected = processor._resolve_harness_model(
        "mode-expert",
        "mode-thread",
        {"work_mode": "deep_research"},
        needs_multimodal=False,
        user_id=owner,
        text="继续",
    )
    assert selected == "Owned/coder-lite"
