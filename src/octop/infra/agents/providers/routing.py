"""Account-owned task model preferences and explainable turn admission routing."""

from __future__ import annotations

import logging
import re
from typing import Annotated, Any, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    field_validator,
)

from octop.infra.agents.providers.model_flags import is_vision_model
from octop.infra.agents.providers.resolved import list_resolved_models
from octop.infra.agents.providers.store import ProviderStore
from octop.infra.db.services import RepoBundle
from octop.infra.errors import ErrorCode, OctopError

logger = logging.getLogger(__name__)

ModelTask = Literal[
    "chat",
    "coding",
    "reasoning",
    "research",
    "vision",
    "long_context",
    "title",
    "summary",
    "memory",
]
MODEL_TASKS: tuple[ModelTask, ...] = (
    "chat",
    "coding",
    "reasoning",
    "research",
    "vision",
    "long_context",
    "title",
    "summary",
    "memory",
)
ModelRef = Annotated[str, StringConstraints(strip_whitespace=True, max_length=300)]
_CODING = re.compile(
    r"```|代码|编程|脚本|报错|调试|重构|代码库|单元测试|(?:\b(?:code|coding|implement|script|bug|debug|traceback|python|typescript|javascript|golang|sql|refactor)\b)",
    re.I,
)
_RESEARCH = re.compile(
    r"搜索|检索|调研|查找资料|查证|文献|资料来源|\b(?:research|citation|search)\b", re.I
)
_REASONING = re.compile(r"推理|证明|数学|推导|演算|\b(?:prove|reasoning|calculate)\b", re.I)
_DELIBERATION = re.compile(
    r"架构(?:设计|决策|分析|评审)?|核心(?:部分)?设计|技术选型|方案(?:设计|权衡|评估|分析)"
    r"|(?:实验|研究)(?:设计|方案|规划|优先级|潜力|假设|结果分析)"
    r"|(?:分析|评估|解释|判读)(?:[^\n]{0,24})(?:实验|结果|指标|现象|基线|创新|假设)"
    r"|实验[^\n]{0,40}(?:失败|分析|评估|优化方案)"
    r"|(?:重要|关键|核心)(?:的)?决策|创新(?:方向|潜力|分析)|前置(?:依赖)?图"
    r"|\b(?:architect(?:ure|ural)?|design\s+(?:decision|tradeoff|experiment)"
    r"|design\s+(?:a\s+)?core\s+(?:component|system)"
    r"|experiment(?:al)?\s+(?:design|analysis|planning|results?)"
    r"|(?:analy[sz]e|evaluat\w*)\s+(?:the\s+)?(?:experiment|hypothesis|results?))\b",
    re.I,
)


class ModelRoutingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    enabled: bool = False
    tasks: dict[ModelTask, ModelRef | None] = Field(default_factory=dict)

    @field_validator("tasks")
    @classmethod
    def normalize_choices(cls, tasks: dict[ModelTask, str | None]) -> dict[ModelTask, str | None]:
        return {
            task: (ref if ref and ref.lower() != "auto" else None) for task, ref in tasks.items()
        }


class ModelRouteDecision(BaseModel):
    task: ModelTask
    model: str | None
    source: Literal["manual", "task", "automatic", "default"]
    reason: str
    available: bool


class ModelRoutingView(ModelRoutingConfig):
    models: list[dict[str, Any]]
    resolved: dict[ModelTask, ModelRouteDecision]
    memory_apply: Literal["next_expert_reload"] = "next_expert_reload"
    auxiliary_overrides: dict[ModelTask, str] = Field(default_factory=dict)


class ModelRoutePreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(default="", max_length=20000)
    task: ModelTask | None = None
    model: ModelRef | None = None
    has_images: bool = False
    work_mode: str | None = Field(default=None, max_length=40)
    context_tokens: int = Field(default=0, ge=0, le=10000000)


def routing_input(messages: Any) -> tuple[str, bool]:
    """Only the newest user message classifies a new turn, never tool output."""
    if isinstance(messages, str):
        return messages, False
    if not isinstance(messages, list):
        return "", False
    for message in reversed(messages):
        role = message.get("role") if isinstance(message, dict) else getattr(message, "type", None)
        if role not in {"user", "human"}:
            continue
        content = (
            message.get("content", "")
            if isinstance(message, dict)
            else getattr(message, "content", "")
        )
        if isinstance(content, str):
            return content, False
        if isinstance(content, list):
            blocks = [block for block in content if isinstance(block, dict)]
            return "\n".join(
                str(block.get("text", ""))
                for block in blocks
                if block.get("type") in {"text", "input_text"}
            ), any(block.get("type") in {"image", "image_url", "input_image"} for block in blocks)
    return "", False


def classify_model_task(
    text: str, *, has_images: bool = False, work_mode: str | None = None, context_tokens: int = 0
) -> ModelTask:
    if has_images or work_mode == "computer_use":
        return "vision"
    if work_mode == "deep_research":
        return "research"
    if (
        work_mode in {"plan", "multitask", "team"}
        or _DELIBERATION.search(text)
        or _REASONING.search(text)
    ):
        return "reasoning"
    if work_mode == "debug" or _CODING.search(text):
        return "coding"
    if _RESEARCH.search(text):
        return "research"
    if context_tokens >= 32768:
        return "long_context"
    return "chat"


class ModelRoutingService:
    def __init__(self, repos: RepoBundle, owner: int) -> None:
        self.repos, self.owner = repos, owner
        self.providers = ProviderStore(repos.provider_repo, owner)

    @property
    def key(self) -> str:
        return f"model_routing.user.{self.owner}"

    def config(self) -> ModelRoutingConfig:
        raw = self.repos.settings_repo.get(self.key)
        if not raw:
            return ModelRoutingConfig()
        try:
            return ModelRoutingConfig.model_validate_json(raw)
        except (ValidationError, ValueError):
            logger.warning(
                "Invalid model routing config for owner=%s; using legacy defaults", self.owner
            )
            return ModelRoutingConfig()

    def models(self) -> list[dict[str, Any]]:
        result = []
        for item in list_resolved_models(list(self.providers.iter_usable_rows())):
            inputs = list(item.get("input") or ["text"])
            if is_vision_model({**item, "id": item["model"]}) and "image" not in inputs:
                inputs.append("image")
            result.append(
                {**item, "input": inputs, "value": f"{item['provider_name']}/{item['model']}"}
            )
        return result

    def default_model(self) -> str | None:
        name, model = self.repos.settings_repo.get_active_model(self.owner)
        ref = f"{name}/{model}" if name and model else ""
        return (
            ref
            if ref and self.providers.is_model_ref_usable(ref)
            else self.providers.resolve_first_model_ref()
        )

    def context_budget(self, agent_id: str, thread_id: str, text: str) -> int:
        from math import ceil

        from octop_harness.context_usage import estimate_tokens

        recent = self.repos.request_snapshot_repo.list(self.owner, agent_id, thread_id, limit=1)
        previous = recent[0] if recent else {}
        usage = previous.get("actual_usage") or {}
        return (
            int(usage.get("input_tokens") or previous.get("estimated_input_tokens") or 0)
            + int(usage.get("output_tokens") or 0)
            + ceil(estimate_tokens(text) * 1.5)
        )

    def save(self, config: ModelRoutingConfig) -> ModelRoutingView:
        existing = self.config().tasks
        for task, ref in config.tasks.items():
            if (
                ref
                and (ref != existing.get(task))
                and (
                    not self.providers.is_model_ref_usable(ref)
                    or (task == "vision" and not self.providers.is_model_ref_multimodal(ref))
                )
            ):
                raise OctopError.localized(ErrorCode.MODEL_ROUTING_INVALID_MODEL)
        self.repos.settings_repo.set(self.key, config.model_dump_json())
        return self.view()

    def view(self) -> ModelRoutingView:
        config = self.config()
        models = self.models()
        return ModelRoutingView(
            **config.model_dump(),
            models=models,
            resolved={
                task: self.resolve(task=task, models=models, honor_auxiliary_settings=True)
                for task in MODEL_TASKS
            },
            auxiliary_overrides=self.auxiliary_overrides(),
        )

    def auxiliary_overrides(self) -> dict[ModelTask, str]:
        settings = self.repos.conversation_metadata_repo.settings(self.owner)
        choices: tuple[tuple[ModelTask, str, str], ...] = (
            ("title", "title_model", "account"),
            ("summary", "brief_model", "same"),
        )
        return {
            task: str(settings.get(field, default))
            for task, field, default in choices
            if settings.get(field, default) != "account"
        }

    def resolve(
        self,
        *,
        task: ModelTask | None = None,
        text: str = "",
        has_images: bool = False,
        work_mode: str | None = None,
        context_tokens: int = 0,
        explicit_model: str | None = None,
        default_model: str | None = None,
        models: list[dict[str, Any]] | None = None,
        honor_auxiliary_settings: bool = False,
    ) -> ModelRouteDecision:
        kind = task or classify_model_task(
            text, has_images=has_images, work_mode=work_mode, context_tokens=context_tokens
        )
        config = self.config()
        candidates = models if models is not None else self.models()
        by_ref = {item["value"]: item for item in candidates}
        default = default_model if default_model in by_ref else self.default_model()
        image_required = has_images or kind == "vision"

        def fits_image(ref: str | None) -> bool:
            return bool(
                ref in by_ref
                and (
                    not image_required
                    or is_vision_model({**by_ref[ref], "id": by_ref[ref]["model"]})
                )
            )

        def decision(
            ref: str | None, source: Literal["manual", "task", "automatic", "default"], reason: str
        ) -> ModelRouteDecision:
            return ModelRouteDecision(
                task=kind, model=ref, source=source, reason=reason, available=fits_image(ref)
            )

        if honor_auxiliary_settings and kind in {"title", "summary"}:
            override = self.auxiliary_overrides().get(kind)
            if override == "same":
                title = self.resolve(task="title", models=candidates, honor_auxiliary_settings=True)
                return decision(title.model, "manual", "same_as_title")
            if override:
                return decision(
                    override if override in by_ref else None, "manual", "dedicated_setting"
                )

        if explicit_model in by_ref:
            return decision(explicit_model, "manual", "manual")
        if not config.enabled:
            return decision(default, "default", "routing_disabled")
        preferred = config.tasks.get(kind)
        if preferred in by_ref and fits_image(preferred):
            return decision(preferred, "task", "task_model")

        def cap(item: dict[str, Any]) -> int:
            value = item.get("max_input_tokens") or item.get("context_window")
            return (
                value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else 0
            )

        eligible = [
            item
            for item in candidates
            if fits_image(item["value"])
            and (not context_tokens or not cap(item) or cap(item) >= context_tokens)
        ]
        compatible_default = default if any(item["value"] == default for item in eligible) else None
        if image_required:
            selected = (
                compatible_default
                if compatible_default
                else (eligible[0]["value"] if eligible else None)
            )
            return decision(
                selected, "automatic", "image_capability" if selected else "no_compatible_model"
            )
        if kind == "reasoning":
            capable = [item for item in eligible if item.get("reasoning")]
            if capable:
                selected = (
                    default
                    if any(item["value"] == default for item in capable)
                    else capable[0]["value"]
                )
                return decision(selected, "automatic", "reasoning_capability")
        if kind == "coding":
            specialists = [
                item
                for item in eligible
                if any(
                    tag in str(item.get("model", "")).lower()
                    for tag in ("coder", "codestral", "codex")
                )
            ]
            if specialists:
                selected = (
                    default
                    if any(item["value"] == default for item in specialists)
                    else specialists[0]["value"]
                )
                return decision(selected, "automatic", "coding_model")
        if context_tokens and not compatible_default:
            fitting = [item for item in eligible if cap(item) >= context_tokens]
            if fitting:
                selected = (
                    default
                    if any(item["value"] == default for item in fitting)
                    else min(fitting, key=cap)["value"]
                )
                return decision(selected, "automatic", "context_capacity")
        return decision(
            compatible_default or default,
            "automatic",
            "unavailable_task_model" if preferred else "account_default",
        )
