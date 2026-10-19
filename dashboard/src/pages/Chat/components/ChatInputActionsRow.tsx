import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import {
  Send,
  Square,
  MessageSquarePlus,
  Paperclip,
  Zap,
  Link2,
  Sparkles,
  Wand2,
  Mic,
  CircleDot,
  Play,
  Loader2,
  Cpu,
  Brain,
  GraduationCap,
  BookOpen,
  Bot,
  Plus,
  Check,
  ChevronLeft,
  ChevronRight,
  ChevronDown,
  Route,
  Info,
  AtSign,
  ListPlus,
} from "lucide-react";
import { Tooltip, Popover } from "antd";
import { message } from "@/utils/antdMessage";
import type { ResolvedModel } from "../../../api/types";
import type { KnowledgeBase } from "../../../api/modules/knowledgeBases";
import type { SkillSpec } from "../../Agent/Skills/useSkills";
import type { ChatAgentOption } from "./ExpertAgentAvatar";
import type { AgentSubagentSummary } from "../../../api/modules/subagents";
import {
  modelOptionLabel,
  modelOptionValue,
  modelShortLabel,
} from "../../../utils/modelOptions";
import { customProviderLogo, getProviderLogo } from "../../../assets/providers";
import ContextWindowRing from "./ContextWindowRing";
import SkillPickerPopover from "./SkillPickerPopover";
import ExpertPickerPopover from "./ExpertPickerPopover";
import SubagentPickerPopover from "./SubagentPickerPopover";
import ConnectorPickerPopover from "./ConnectorPickerPopover";
import KnowledgePickerPopover from "./KnowledgePickerPopover";
import { ConversationModeMenu, workModeIcon } from "./ConversationModePicker";
import type { WorkMode } from "../utils/workMode";
import HitlPolicyPicker from "./HitlPolicyPicker";
import SlashCommandMenu from "./SlashCommandMenu";
import type { SlashMenuGroup } from "../../../utils/slashCategories";
import type { SlashMenuItem } from "../hooks/useSlashMentionInput";
import type { HitlSessionPolicy } from "../utils/hitlSessionPolicy";
import { SHORTCUT_ICON_TONE_CLASS } from "../utils/slashShortcutStyles";
import { isSttAvailable } from "../../../hooks/useVoiceInput";
import { parseSkillSlugsInText } from "../utils/skillSlash";
import { useSkillDisplayName } from "../../Agent/Skills/skillDisplayNames";
import {
  mentionedExpertIds,
  mentionedSubagentSlugs,
} from "../utils/expertMention";
import styles from "../index.module.less";

/** The same picker panels are used by desktop buttons and compact overflow. */
type CompactPickerKey =
  | "mode"
  | "model"
  | "connector"
  | "knowledge"
  | "skill"
  | "expert"
  | "subagent"
  | "shortcut";

function resolveModelLogo(model: {
  provider_name: string;
  provider_kind: string;
}): string {
  const name = model.provider_name;
  const slug = name.toLowerCase().replace(/\s+/g, "-");
  return (
    getProviderLogo(name) ??
    getProviderLogo(name.toLowerCase()) ??
    getProviderLogo(slug) ??
    getProviderLogo(model.provider_kind) ??
    customProviderLogo
  );
}

// These browser APIs never change at runtime — compute once.
const _sttAvailable = isSttAvailable();

interface ChatInputActionsRowProps {
  isMobile: boolean;
  isStreaming: boolean;
  /** Team host room — stop control uses clearer wording. */
  isTeam?: boolean;
  disabled?: boolean;
  canSend: boolean;
  text: string;
  polishing: boolean;
  uploading: boolean;
  recording: boolean;
  transcribing: boolean;
  browserRecording?: boolean;
  browserReplayBusy?: boolean;
  browserLastRecordingId?: string | null;
  onStartBrowserRecording?: () => void;
  onStopBrowserRecording?: () => void;
  onReplayBrowserRecording?: () => void;
  agentId?: string | null;
  threadId?: string | null;
  contextUsedTokens?: number | null;
  contextMaxTokens?: number;
  onInspectContext?: () => void;
  deviceControl?: React.ReactNode;
  availableModels?: ResolvedModel[];
  selectedModel?: string | null;
  defaultModel?: string | null;
  onModelChange?: (model: string | null) => void;
  reasoningMode?: "auto" | "enabled" | "disabled";
  reasoningEffort?: string | null;
  onReasoningChange?: (
    mode: "auto" | "enabled" | "disabled",
    effort: string | null,
  ) => void;
  conversationMode?: "ask" | "plan" | "craft";
  onConversationModeChange?: (mode: "ask" | "plan" | "craft") => void;
  workMode?: WorkMode;
  onWorkModeChange?: (mode: WorkMode) => void;
  hitlPolicy?: HitlSessionPolicy;
  onHitlPolicyChange?: (policy: HitlSessionPolicy) => void;
  availableConnectors?: {
    mcp_server_name: string;
    label: string;
    kind: string;
  }[];
  selectedConnectors?: string[];
  onConnectorsChange?: (names: string[]) => void;
  availableKnowledgeBases?: KnowledgeBase[];
  selectedKnowledgeBaseIds?: string[];
  onKnowledgeBaseIdsChange?: (ids: string[]) => void;
  availableSkills?: SkillSpec[];
  onInsertSkillCommand?: (slug: string) => void;
  availableExperts?: ChatAgentOption[];
  onInsertExpertMention?: (agent: ChatAgentOption) => void;
  availableSubagents?: AgentSubagentSummary[];
  onInsertSubagentMention?: (subagent: AgentSubagentSummary) => void;
  slashPickerGroups: SlashMenuGroup<SlashMenuItem>[] | null;
  slashMenuItems: SlashMenuItem[];
  onSlashShortcutSelect: (command: string) => void;
  onFileSelect: () => void;
  onNewChat: () => void;
  onPolish: () => void;
  onToggleVoice: () => void;
  onCancel: () => void;
  onSubmit: () => void;
}

export default function ChatInputActionsRow({
  isMobile,
  isStreaming,
  isTeam = false,
  disabled,
  canSend,
  text,
  polishing,
  uploading,
  recording,
  transcribing,
  browserRecording = false,
  browserReplayBusy = false,
  browserLastRecordingId = null,
  onStartBrowserRecording,
  onStopBrowserRecording,
  onReplayBrowserRecording,
  agentId,
  threadId,
  contextUsedTokens = null,
  contextMaxTokens = 128_000,
  onInspectContext,
  deviceControl,
  availableModels,
  selectedModel,
  defaultModel,
  onModelChange,
  reasoningMode = "auto",
  reasoningEffort = null,
  onReasoningChange,
  conversationMode = "craft",
  onConversationModeChange,
  workMode = conversationMode === "craft" ? "agentic" : conversationMode,
  onWorkModeChange,
  hitlPolicy,
  onHitlPolicyChange,
  availableConnectors,
  selectedConnectors = [],
  onConnectorsChange,
  availableKnowledgeBases,
  selectedKnowledgeBaseIds = [],
  onKnowledgeBaseIdsChange,
  availableSkills,
  onInsertSkillCommand,
  availableExperts,
  onInsertExpertMention,
  availableSubagents,
  onInsertSubagentMention,
  slashPickerGroups,
  slashMenuItems,
  onSlashShortcutSelect,
  onFileSelect,
  onNewChat,
  onPolish,
  onToggleVoice,
  onCancel,
  onSubmit,
}: ChatInputActionsRowProps) {
  const { t } = useTranslation();
  const navigate = useNavigate();
  const remoteManaged = Boolean(agentId?.startsWith("bridge:"));
  const skillDisplayName = useSkillDisplayName();
  const actionsRowRef = useRef<HTMLDivElement | null>(null);
  const [plusMenuEl, setPlusMenuEl] = useState<HTMLDivElement | null>(null);
  const [plusMenuHeight, setPlusMenuHeight] = useState<number | null>(null);
  const [isCompact, setIsCompact] = useState(false);
  const [memberPickerOpen, setMemberPickerOpen] = useState(false);
  const [reasoningModelRef, setReasoningModelRef] = useState<string | null>(
    null,
  );
  /** Plus-button menu (model / skills / …). */
  const [overflowPopoverOpen, setOverflowPopoverOpen] = useState(false);
  /** Picker panel opened from a plus-menu item. */
  const [compactPicker, setCompactPicker] = useState<CompactPickerKey | null>(
    null,
  );

  const useCompactControls = isMobile || isCompact;

  useEffect(() => {
    setOverflowPopoverOpen(false);
    setCompactPicker(null);
    setReasoningModelRef(null);
  }, [useCompactControls]);

  useLayoutEffect(() => {
    if (!plusMenuEl || isMobile) {
      setPlusMenuHeight(null);
      return;
    }
    const sync = () => {
      const next = Math.round(plusMenuEl.getBoundingClientRect().height);
      if (next <= 0) return;
      setPlusMenuHeight((prev) => (prev === next ? prev : next));
    };
    sync();
    const observer = new ResizeObserver(sync);
    observer.observe(plusMenuEl);
    return () => observer.disconnect();
  }, [plusMenuEl, isMobile]);

  useEffect(() => {
    if (isMobile) {
      setIsCompact(false);
      return;
    }
    const row = actionsRowRef.current;
    if (!row) return;
    const update = (width: number) => {
      if (width > 0) setIsCompact(width <= 800);
    };
    update(row.getBoundingClientRect().width);
    const observer = new ResizeObserver(([entry]) => {
      if (entry) update(entry.contentRect.width);
    });
    observer.observe(row);
    return () => observer.disconnect();
  }, [isMobile]);

  const showModelPicker = Boolean(
    availableModels && availableModels.length > 0 && onModelChange,
  );
  const allowWriteTools = conversationMode === "craft";
  const showConnectorPicker = Boolean(
    allowWriteTools && availableConnectors && onConnectorsChange,
  );
  const showKnowledgePicker = Boolean(
    availableKnowledgeBases && onKnowledgeBaseIdsChange,
  );
  const showSkillPicker = Boolean(
    allowWriteTools && availableSkills && onInsertSkillCommand,
  );
  const showExpertPicker = Boolean(
    allowWriteTools &&
      availableExperts &&
      onInsertExpertMention &&
      availableExperts.length > 0,
  );
  const showSubagentPicker = Boolean(
    allowWriteTools &&
      availableSubagents &&
      onInsertSubagentMention &&
      availableSubagents.length > 0,
  );
  const mentionedExperts = mentionedExpertIds(text, availableExperts ?? []);
  const mentionedSubagents = mentionedSubagentSlugs(
    text,
    availableSubagents ?? [],
  );
  const skillTokenRefs = useMemo(
    () =>
      (availableSkills ?? []).map((skill) => ({
        slug: skill.slug,
        label: skillDisplayName(skill),
        emoji: skill.emoji,
      })),
    [availableSkills, skillDisplayName],
  );
  const activeSkillSlugs = parseSkillSlugsInText(text, skillTokenRefs);
  const showModePicker = Boolean(onConversationModeChange);
  const showOverflowMenu =
    useCompactControls ||
    showModePicker ||
    showConnectorPicker ||
    showKnowledgePicker ||
    showSkillPicker ||
    showExpertPicker ||
    showSubagentPicker ||
    slashMenuItems.length > 0;

  const overflowBadgeCount =
    selectedConnectors.length +
    selectedKnowledgeBaseIds.length +
    activeSkillSlugs.length +
    mentionedExperts.length +
    mentionedSubagents.length;

  const closeCompactPicker = () => {
    setCompactPicker(null);
    setReasoningModelRef(null);
  };

  const closePlusMenu = () => {
    setOverflowPopoverOpen(false);
    closeCompactPicker();
  };

  const openCompactPicker = (key: CompactPickerKey) => {
    setReasoningModelRef(null);
    setCompactPicker((prev) => (prev === key ? null : key));
  };

  const handleExpertSelect = (agent: ChatAgentOption) => {
    onInsertExpertMention?.(agent);
    closePlusMenu();
  };

  const handleSubagentSelect = (subagent: AgentSubagentSummary) => {
    onInsertSubagentMention?.(subagent);
    closePlusMenu();
  };

  const compactPickerTitle: Record<CompactPickerKey, string> = {
    mode: t("chat.conversationMode.picker"),
    model: t("chat.selectModel", "Model"),
    connector: t("connectors.chatPicker"),
    knowledge: t("chat.knowledgePicker"),
    skill: t("chat.skillPicker"),
    expert: t("chat.expertPicker"),
    subagent: t("chat.subagentPicker"),
    shortcut: t("shortcut.title", "快捷指令"),
  };

  const reasoningModel = availableModels?.find(
    (model) => modelOptionValue(model) === reasoningModelRef,
  );
  const reasoningModelCapability = reasoningModel?.reasoning_config;

  const reasoningModeLabel = (mode: "auto" | "enabled" | "disabled") =>
    mode === "auto"
      ? t("chat.reasoningAuto", "自动")
      : mode === "enabled"
      ? t("chat.reasoningEnabled", "开启")
      : t("chat.reasoningDisabled", "关闭");

  const effectiveModelRef = selectedModel || defaultModel;
  const effectiveModel = availableModels?.find(
    (model) =>
      modelOptionValue(model) === effectiveModelRef ||
      (!selectedModel && model.model === effectiveModelRef),
  );
  const effectiveModelLabel = effectiveModel
    ? effectiveModel.name || effectiveModel.model
    : selectedModel
    ? modelShortLabel(selectedModel)
    : null;
  const autoModelLabel = t("chat.modelAuto", "Auto");
  const selectedModelTriggerLabel = selectedModel
    ? effectiveModelLabel || modelShortLabel(selectedModel)
    : effectiveModelLabel
    ? `${autoModelLabel} · ${effectiveModelLabel}`
    : autoModelLabel;
  const selectedModelDetail = effectiveModel
    ? modelOptionLabel(effectiveModel)
    : selectedModel;
  const selectedModelTooltip = selectedModel
    ? selectedModelDetail || selectedModelTriggerLabel
    : `${autoModelLabel}: ${t("chat.modelAutoHint", "Use agent default")}${
        selectedModelDetail ? ` · ${selectedModelDetail}` : ""
      }`;

  const reasoningSummary = (model: ResolvedModel, active: boolean) => {
    const capability = model.reasoning_config;
    if (!capability) return null;
    if (capability.adapter === "status_only") {
      return t("chat.reasoningAlways", "始终推理");
    }
    if (active) {
      return reasoningEffort || reasoningModeLabel(reasoningMode);
    }
    return (
      capability.default_effort ||
      reasoningModeLabel(capability.default_mode || "auto")
    );
  };

  const openModelReasoning = (modelRef: string) => {
    if (selectedModel !== modelRef) onModelChange?.(modelRef);
    setReasoningModelRef(modelRef);
  };

  const reasoningMenu = reasoningModelCapability ? (
    <div className={styles.reasoningMenuPanel}>
      <div className={styles.reasoningMenuHeader}>
        <button
          type="button"
          className={styles.reasoningMenuBack}
          onClick={() => setReasoningModelRef(null)}
          aria-label={t("common.back", "返回")}
        >
          <ChevronLeft size={16} />
        </button>
        <span>{reasoningModel ? modelOptionLabel(reasoningModel) : ""}</span>
      </div>
      {reasoningModelCapability.adapter === "status_only" ? (
        <div className={styles.reasoningStatusRow}>
          <Brain size={16} />
          <span>{t("chat.reasoningAlways", "始终推理")}</span>
          <Check size={16} />
        </div>
      ) : (
        <>
          <div className={styles.reasoningMenuSectionLabel}>
            {t("chat.reasoningMode", "思考模式")}
          </div>
          {(reasoningModelCapability.toggle
            ? (["auto", "enabled", "disabled"] as const)
            : (["auto", "enabled"] as const)
          ).map((mode) => (
            <button
              key={mode}
              type="button"
              className={`${styles.reasoningMenuChoice} ${
                reasoningMode === mode ? styles.reasoningMenuChoiceActive : ""
              }`}
              onClick={() => onReasoningChange?.(mode, reasoningEffort)}
            >
              <span>{reasoningModeLabel(mode)}</span>
              {reasoningMode === mode && <Check size={16} />}
            </button>
          ))}
          {reasoningModelCapability.efforts.length > 0 && (
            <>
              <div className={styles.reasoningMenuDivider} />
              <div className={styles.reasoningMenuSectionLabel}>
                {t("chat.reasoningEffort", "思考强度")}
              </div>
              {reasoningModelCapability.efforts.map((effort) => (
                <button
                  key={effort}
                  type="button"
                  className={`${styles.reasoningMenuChoice} ${
                    reasoningEffort === effort
                      ? styles.reasoningMenuChoiceActive
                      : ""
                  }`}
                  onClick={() =>
                    onReasoningChange?.(
                      reasoningMode === "disabled" ? "enabled" : reasoningMode,
                      effort,
                    )
                  }
                >
                  <span>{effort}</span>
                  {reasoningEffort === effort && <Check size={16} />}
                </button>
              ))}
            </>
          )}
        </>
      )}
    </div>
  ) : null;

  const modelMenu = (
    <div className={styles.modelPickerPanel}>
      {!reasoningMenu && (
        <div className={styles.modelMenuColumn}>
          <div className={styles.modelMenu}>
            <button
              type="button"
              className={`${styles.modelMenuItem} ${
                !selectedModel ? styles.modelMenuItemActive : ""
              }`}
              onClick={() => {
                onModelChange?.(null);
                closePlusMenu();
              }}
            >
              <span className={styles.modelMenuTitle}>
                <Route size={16} aria-hidden />
                <span className={styles.modelMenuLabel}>
                  {t("chat.modelAuto", "Auto")}
                </span>
              </span>
              <span className={styles.modelMenuHint}>
                {t("chat.modelAutoHint", "Use agent default")}
              </span>
            </button>
            {availableModels?.map((model) => {
              const value = modelOptionValue(model);
              const active = selectedModel === value;
              const capability = model.reasoning_config;
              const summary = reasoningSummary(model, active);
              return (
                <div
                  key={value}
                  className={`${styles.modelMenuRow} ${
                    active ? styles.modelMenuItemActive : ""
                  }`}
                >
                  <button
                    type="button"
                    className={styles.modelMenuSelect}
                    onClick={() => {
                      onModelChange?.(active ? null : value);
                      closePlusMenu();
                    }}
                  >
                    <img
                      src={resolveModelLogo(model)}
                      alt=""
                      className={styles.modelMenuIcon}
                    />
                    <span className={styles.modelMenuLabel}>
                      {modelOptionLabel(model)}
                    </span>
                  </button>
                  {capability && onReasoningChange && (
                    <button
                      type="button"
                      className={styles.modelMenuReasoning}
                      onClick={() => openModelReasoning(value)}
                      aria-label={`${modelOptionLabel(model)} ${t(
                        "chat.reasoningMode",
                        "思考模式",
                      )}`}
                    >
                      <Brain size={14} />
                      {summary && <span>{summary}</span>}
                      {capability.adapter !== "status_only" && (
                        <ChevronRight size={15} />
                      )}
                    </button>
                  )}
                </div>
              );
            })}
          </div>
          <div className={styles.modelMenuDivider} />
          <button
            type="button"
            className={`${styles.modelMenuFooter} ${
              remoteManaged ? styles.modelMenuFooterMuted : ""
            }`}
            onClick={() => {
              if (remoteManaged) {
                message.info(t("chat.remoteExpert.manageToast"));
                return;
              }
              closePlusMenu();
              navigate("/admin/models");
            }}
          >
            {remoteManaged ? (
              <Info size={15} aria-hidden />
            ) : (
              <Cpu size={15} aria-hidden />
            )}
            <span>
              {remoteManaged
                ? t("chat.remoteExpert.manageOnPeer")
                : t("chat.modelPickerManage")}
            </span>
          </button>
        </div>
      )}
      {reasoningMenu}
    </div>
  );

  const shortcutMenu = (
    <div className={styles.shortcutPickerPanel}>
      <div className={styles.skillPickerList}>
        <SlashCommandMenu
          groups={slashPickerGroups}
          flatItems={slashMenuItems}
          activeIndex={-1}
          disabled={isStreaming || disabled}
          variant="popover"
          itemsGridClassName={styles.slashMenuGrid}
          itemClassName={styles.slashPickerItem}
          activeClassName=""
          categoryClassName={styles.slashMenuCategory}
          labelClassName={styles.skillPickerText}
          nameClassName={styles.skillPickerName}
          cmdClassName={styles.skillPickerDesc}
          iconWrapClassName={(tone) =>
            `${styles.shortcutPickerIcon} ${
              SHORTCUT_ICON_TONE_CLASS[tone] ?? styles.shortcutPickerIconBlue
            }`
          }
          onSelect={(command) => {
            closePlusMenu();
            onSlashShortcutSelect(command);
          }}
          onHover={() => undefined}
        />
      </div>
    </div>
  );

  const ModeIcon = workModeIcon(workMode);

  const renderPlusMenu = () => (
    <div className={styles.mobileOverflowMenu}>
      <button
        type="button"
        className={styles.mobileOverflowItem}
        aria-label={t("chatWelcome.newChat")}
        onClick={() => {
          closePlusMenu();
          onNewChat();
        }}
      >
        <span className={styles.mobileOverflowItemMain}>
          <MessageSquarePlus size={16} />
          <span>{t("chatWelcome.newChat")}</span>
        </span>
      </button>
      {onHitlPolicyChange && (
        <div className={styles.mobileOverflowItem}>
          <span className={styles.mobileOverflowItemMain}>
            {t("chat.hitl.policy.picker")}
          </span>
          <HitlPolicyPicker
            policy={hitlPolicy ?? { mode: "ask" }}
            onChange={onHitlPolicyChange}
          />
        </div>
      )}
      {showModePicker && (
        <button
          type="button"
          className={`${styles.mobileOverflowItem} ${
            compactPicker === "mode" ? styles.mobileOverflowItemActive : ""
          }`}
          onClick={() => openCompactPicker("mode")}
        >
          <span className={styles.mobileOverflowItemMain}>
            <ModeIcon size={16} />
            <span>{t("chat.conversationMode.picker")}</span>
          </span>
          <span className={styles.mobileOverflowItemMeta}>
            <span className={styles.mobileOverflowItemMetaLabel}>
              {t(`chat.workMode.${workMode}`)}
            </span>
            <ChevronRight size={16} />
          </span>
        </button>
      )}
      {showConnectorPicker && (
        <button
          type="button"
          className={`${styles.mobileOverflowItem} ${
            compactPicker === "connector" ? styles.mobileOverflowItemActive : ""
          }`}
          onClick={() => openCompactPicker("connector")}
        >
          <span className={styles.mobileOverflowItemMain}>
            <Link2 size={16} />
            <span>{t("connectors.chatPicker")}</span>
          </span>
          <span className={styles.mobileOverflowItemMeta}>
            {selectedConnectors.length > 0 && (
              <span className={styles.toolbarBadge}>
                {selectedConnectors.length}
              </span>
            )}
            <ChevronRight size={16} />
          </span>
        </button>
      )}
      {showKnowledgePicker && (
        <button
          type="button"
          className={`${styles.mobileOverflowItem} ${
            compactPicker === "knowledge" ? styles.mobileOverflowItemActive : ""
          }`}
          onClick={() => openCompactPicker("knowledge")}
        >
          <span className={styles.mobileOverflowItemMain}>
            <BookOpen size={16} />
            <span>{t("chat.knowledgePicker")}</span>
          </span>
          <span className={styles.mobileOverflowItemMeta}>
            {selectedKnowledgeBaseIds.length > 0 && (
              <span className={styles.toolbarBadge}>
                {selectedKnowledgeBaseIds.length}
              </span>
            )}
            <ChevronRight size={16} />
          </span>
        </button>
      )}
      {showSkillPicker && (
        <button
          type="button"
          className={`${styles.mobileOverflowItem} ${
            compactPicker === "skill" ? styles.mobileOverflowItemActive : ""
          }`}
          onClick={() => openCompactPicker("skill")}
        >
          <span className={styles.mobileOverflowItemMain}>
            <Sparkles size={16} />
            <span>{t("chat.skillPicker")}</span>
          </span>
          <span className={styles.mobileOverflowItemMeta}>
            {activeSkillSlugs.length > 0 ? (
              <span className={styles.toolbarBadge}>
                {activeSkillSlugs.length}
              </span>
            ) : null}
            <ChevronRight size={16} />
          </span>
        </button>
      )}
      {showExpertPicker && (
        <button
          type="button"
          className={`${styles.mobileOverflowItem} ${
            compactPicker === "expert" ? styles.mobileOverflowItemActive : ""
          }`}
          onClick={() => openCompactPicker("expert")}
        >
          <span className={styles.mobileOverflowItemMain}>
            <GraduationCap size={16} />
            <span>{t("chat.expertPicker")}</span>
          </span>
          <span className={styles.mobileOverflowItemMeta}>
            {mentionedExperts.length > 0 && (
              <span
                className={`${styles.toolbarBadge} ${styles.toolbarBadgeExpert}`}
              >
                {mentionedExperts.length}
              </span>
            )}
            <ChevronRight size={16} />
          </span>
        </button>
      )}
      {showSubagentPicker && (
        <button
          type="button"
          className={`${styles.mobileOverflowItem} ${
            compactPicker === "subagent" ? styles.mobileOverflowItemActive : ""
          }`}
          onClick={() => openCompactPicker("subagent")}
        >
          <span className={styles.mobileOverflowItemMain}>
            <Bot size={16} />
            <span>{t("chat.subagentPicker")}</span>
          </span>
          <span className={styles.mobileOverflowItemMeta}>
            {mentionedSubagents.length > 0 && (
              <span
                className={`${styles.toolbarBadge} ${styles.toolbarBadgeSubagent}`}
              >
                {mentionedSubagents.length}
              </span>
            )}
            <ChevronRight size={16} />
          </span>
        </button>
      )}
      {slashMenuItems.length > 0 && (
        <button
          type="button"
          className={`${styles.mobileOverflowItem} ${
            compactPicker === "shortcut" ? styles.mobileOverflowItemActive : ""
          }`}
          onClick={() => openCompactPicker("shortcut")}
        >
          <span className={styles.mobileOverflowItemMain}>
            <Zap size={16} />
            <span>{t("shortcut.title", "快捷指令")}</span>
          </span>
          <ChevronRight size={16} />
        </button>
      )}
    </div>
  );

  const renderCompactPickerContent = (key = compactPicker) => {
    switch (key) {
      case "mode":
        return (
          <ConversationModeMenu
            conversationMode={conversationMode}
            workMode={workMode}
            onWorkModeChange={onWorkModeChange}
            onChange={(mode) => {
              onConversationModeChange?.(mode);
              closePlusMenu();
            }}
          />
        );
      case "model":
        return modelMenu;
      case "connector":
        return (
          <ConnectorPickerPopover
            connectors={availableConnectors ?? []}
            selectedConnectors={selectedConnectors}
            onConnectorsChange={onConnectorsChange!}
            onNavigateAway={closePlusMenu}
          />
        );
      case "knowledge":
        return (
          <KnowledgePickerPopover
            knowledgeBases={availableKnowledgeBases ?? []}
            selectedKnowledgeBaseIds={selectedKnowledgeBaseIds}
            onKnowledgeBaseIdsChange={onKnowledgeBaseIdsChange!}
            onNavigateAway={closePlusMenu}
            remoteManaged={remoteManaged}
          />
        );
      case "skill":
        return (
          <SkillPickerPopover
            skills={availableSkills ?? []}
            activeSlugs={activeSkillSlugs}
            onSelectSkill={(slug) => {
              onInsertSkillCommand?.(slug);
              closePlusMenu();
            }}
            onNavigateAway={closePlusMenu}
            remoteManaged={remoteManaged}
          />
        );
      case "expert":
        return (
          <ExpertPickerPopover
            agents={availableExperts ?? []}
            selectedAgentIds={mentionedExperts}
            onSelect={handleExpertSelect}
            onNavigateAway={closePlusMenu}
            remoteManaged={remoteManaged}
          />
        );
      case "subagent":
        return (
          <SubagentPickerPopover
            subagents={availableSubagents ?? []}
            selectedSlugs={mentionedSubagents}
            onSelect={handleSubagentSelect}
            onNavigateAway={closePlusMenu}
            remoteManaged={remoteManaged}
          />
        );
      case "shortcut":
        return shortcutMenu;
      default:
        return null;
    }
  };

  const desktopPickers = [
    { key: "mode", show: showModePicker, Icon: ModeIcon, count: 0 },
    {
      key: "connector",
      show: showConnectorPicker,
      Icon: Link2,
      count: selectedConnectors.length,
    },
    {
      key: "knowledge",
      show: showKnowledgePicker,
      Icon: BookOpen,
      count: selectedKnowledgeBaseIds.length,
    },
    {
      key: "skill",
      show: showSkillPicker,
      Icon: Sparkles,
      count: activeSkillSlugs.length,
    },
    {
      key: "expert",
      show: showExpertPicker,
      Icon: GraduationCap,
      count: mentionedExperts.length,
    },
    {
      key: "subagent",
      show: showSubagentPicker,
      Icon: Bot,
      count: mentionedSubagents.length,
    },
    { key: "shortcut", show: slashMenuItems.length > 0, Icon: Zap, count: 0 },
  ] as const;

  const renderDesktopPickers = () =>
    desktopPickers.map(({ key, show, Icon, count }) => {
      if (!show) return null;
      const selected = count > 0 || (key === "mode" && workMode !== "agentic");
      const summary = key === "mode" ? t(`chat.workMode.${workMode}`) : null;
      return (
        <Popover
          key={key}
          trigger="click"
          placement="topLeft"
          arrow={false}
          open={compactPicker === key}
          overlayClassName={styles.modelPopover}
          content={renderCompactPickerContent(key)}
          onOpenChange={(open) => {
            setReasoningModelRef(null);
            setCompactPicker(open ? key : null);
          }}
        >
          <Tooltip
            title={
              summary
                ? `${compactPickerTitle[key]}: ${summary}`
                : compactPickerTitle[key]
            }
            mouseEnterDelay={0.4}
          >
            <button
              type="button"
              className={`${styles.secondaryBtn} ${
                styles.composerPickerTrigger
              } ${selected ? styles.secondaryBtnActive : ""}`}
              aria-label={compactPickerTitle[key]}
              aria-expanded={compactPicker === key}
              data-testid={`composer-${key}`}
            >
              <Icon size={15} aria-hidden />
              <span>{compactPickerTitle[key]}</span>
              {count > 0 && (
                <span className={styles.composerPickerCount}>{count}</span>
              )}
            </button>
          </Tooltip>
        </Popover>
      );
    });

  const renderSecondaryActions = () => {
    const plusButton = (
      <button
        className={`${styles.secondaryBtn} ${styles.toolMenuTrigger} ${
          overflowBadgeCount > 0 ? styles.secondaryBtnActive : ""
        }`}
        type="button"
        aria-label={t("chat.composerMore", "更多工具")}
        data-testid="composer-plus"
      >
        <Plus size={16} />
        <span className={styles.toolMenuLabel}>
          {t("chat.composerMore", "更多工具")}
        </span>
        {overflowBadgeCount > 0 && (
          <span className={styles.toolbarBadge}>{overflowBadgeCount}</span>
        )}
      </button>
    );

    return (
      <>
        {isTeam && onInsertExpertMention && (
          <Popover
            trigger="click"
            placement="topLeft"
            open={memberPickerOpen}
            onOpenChange={setMemberPickerOpen}
            content={
              <ExpertPickerPopover
                agents={availableExperts ?? []}
                selectedAgentIds={mentionedExperts}
                onSelect={(agent) => {
                  onInsertExpertMention(agent);
                  setMemberPickerOpen(false);
                }}
                remoteManaged={remoteManaged}
              />
            }
          >
            <button
              type="button"
              className={styles.secondaryBtn}
              aria-label={t("octopus.mentionMember")}
              data-testid="composer-mention"
            >
              <AtSign size={17} />
            </button>
          </Popover>
        )}
        {!useCompactControls && renderDesktopPickers()}
        {useCompactControls && showOverflowMenu && (
          <Popover
            trigger="click"
            placement="topLeft"
            arrow={false}
            open={overflowPopoverOpen}
            overlayClassName={styles.plusMenuPopover}
            content={
              <div className={styles.plusFlyout}>
                {!isMobile || !compactPicker ? (
                  <div ref={setPlusMenuEl} className={styles.plusFlyoutMenu}>
                    {renderPlusMenu()}
                  </div>
                ) : null}
                {compactPicker ? (
                  <div
                    className={
                      isMobile
                        ? styles.plusFlyoutPanelInPlace
                        : styles.plusFlyoutPanel
                    }
                    style={
                      !isMobile && plusMenuHeight
                        ? { maxHeight: plusMenuHeight }
                        : undefined
                    }
                    data-testid="composer-plus-panel"
                  >
                    {isMobile ? (
                      <button
                        type="button"
                        className={styles.compactPickerBack}
                        onClick={closeCompactPicker}
                      >
                        <ChevronLeft size={16} />
                        <span>{compactPickerTitle[compactPicker]}</span>
                      </button>
                    ) : null}
                    <div className={styles.plusFlyoutPanelBody}>
                      {renderCompactPickerContent()}
                    </div>
                  </div>
                ) : null}
              </div>
            }
            onOpenChange={(open) => {
              setOverflowPopoverOpen(open);
              if (!open) closeCompactPicker();
            }}
          >
            <Tooltip
              title={t("chat.composerMore", "更多工具")}
              mouseEnterDelay={0.4}
            >
              {plusButton}
            </Tooltip>
          </Popover>
        )}
        {!useCompactControls && onHitlPolicyChange && (
          <HitlPolicyPicker
            policy={hitlPolicy ?? { mode: "ask" }}
            onChange={onHitlPolicyChange}
          />
        )}
        <Tooltip
          title={t("upload.fileTooltip", "Upload attachment")}
          mouseEnterDelay={0.4}
        >
          <button
            className={styles.secondaryBtn}
            onClick={onFileSelect}
            type="button"
            disabled={uploading}
            aria-label={t("upload.fileTooltip", "Upload attachment")}
          >
            <Paperclip size={16} />
          </button>
        </Tooltip>
      </>
    );
  };

  return (
    <div
      ref={actionsRowRef}
      className={styles.actionsRow}
      data-layout={useCompactControls ? "compact" : "expanded"}
    >
      {showModelPicker && (
        <Popover
          trigger="click"
          placement="topLeft"
          arrow={false}
          open={compactPicker === "model" && !overflowPopoverOpen}
          overlayClassName={styles.modelPopover}
          content={modelMenu}
          onOpenChange={(open) => {
            setOverflowPopoverOpen(false);
            setReasoningModelRef(null);
            setCompactPicker(open ? "model" : null);
          }}
        >
          <Tooltip title={selectedModelTooltip} mouseEnterDelay={0.4}>
            <button
              type="button"
              className={`${styles.secondaryBtn} ${styles.composerPickerTrigger} ${styles.composerModelTrigger}`}
              aria-label={`${compactPickerTitle.model}: ${selectedModelTriggerLabel}`}
              aria-expanded={compactPicker === "model" && !overflowPopoverOpen}
              title={selectedModelTooltip}
              data-testid="composer-model"
            >
              <Cpu size={15} aria-hidden />
              <span className={styles.composerModelLabel}>
                {selectedModelTriggerLabel}
              </span>
              <ChevronDown size={12} aria-hidden />
            </button>
          </Tooltip>
        </Popover>
      )}
      {deviceControl && (
        <div className={styles.composerDeviceControl}>{deviceControl}</div>
      )}
      <div className={styles.secondaryActions}>{renderSecondaryActions()}</div>
      <div className={styles.inputActions}>
        <ContextWindowRing
          selectedModel={effectiveModelRef}
          selectedCapacityTokens={
            effectiveModel?.context_window ??
            effectiveModel?.contextWindow ??
            effectiveModel?.max_input_tokens
          }
          usedTokens={contextUsedTokens}
          maxTokens={contextMaxTokens}
          agentId={agentId}
          threadId={threadId}
          selectedConnectors={selectedConnectors}
          isMobile={isMobile}
          onInspect={onInspectContext}
        />
        {!useCompactControls && text.trim() && !isStreaming ? (
          <Tooltip title={t("chat.polish.tooltip")} mouseEnterDelay={0.4}>
            <button
              className={styles.secondaryBtn}
              onClick={onPolish}
              type="button"
              aria-label={t("chat.polish.tooltip")}
              disabled={
                !text.trim() || polishing || isStreaming || disabled || !agentId
              }
            >
              <Wand2
                size={16}
                className={polishing ? styles.spinIcon : undefined}
              />
            </button>
          </Tooltip>
        ) : null}
        {_sttAvailable && (
          <Tooltip
            title={
              !_sttAvailable
                ? t(
                    "voice.sttNotAvailable",
                    "此设备不支持语音输入（需要 HTTPS）",
                  )
                : recording
                ? t("voice.stopRecording", "停止录音")
                : transcribing
                ? t("voice.transcribing", "识别中…")
                : t("voice.startRecording", "语音输入")
            }
            mouseEnterDelay={0.4}
          >
            <button
              className={`${styles.secondaryBtn} ${
                recording || transcribing ? styles.secondaryBtnActive : ""
              }`}
              type="button"
              disabled={
                disabled || isStreaming || transcribing || !_sttAvailable
              }
              onClick={onToggleVoice}
              aria-label={
                recording
                  ? t("voice.stopRecording", "停止录音")
                  : t("voice.startRecording", "语音输入")
              }
            >
              <Mic size={16} />
            </button>
          </Tooltip>
        )}
        {(onStartBrowserRecording || onStopBrowserRecording) && (
          <Tooltip
            title={
              browserRecording
                ? t("browser.recordReplay.stop", "停止浏览器录制")
                : t("browser.recordReplay.start", "开始浏览器录制")
            }
            mouseEnterDelay={0.4}
          >
            <button
              className={`${styles.secondaryBtn} ${
                browserRecording ? styles.secondaryBtnRecording : ""
              }`}
              type="button"
              disabled={disabled || browserReplayBusy}
              onClick={
                browserRecording
                  ? onStopBrowserRecording
                  : onStartBrowserRecording
              }
            >
              {browserRecording ? (
                <Square size={15} />
              ) : (
                <CircleDot size={16} />
              )}
            </button>
          </Tooltip>
        )}
        {onReplayBrowserRecording && (
          <Tooltip
            title={
              browserLastRecordingId
                ? t("browser.recordReplay.replay", "回放最近一次浏览器录制")
                : t(
                    "browser.recordReplay.noRecording",
                    "请先完成一次浏览器录制",
                  )
            }
            mouseEnterDelay={0.4}
          >
            <button
              className={`${styles.secondaryBtn} ${
                browserReplayBusy ? styles.secondaryBtnActive : ""
              }`}
              type="button"
              disabled={
                disabled ||
                browserRecording ||
                browserReplayBusy ||
                !browserLastRecordingId
              }
              onClick={onReplayBrowserRecording}
            >
              {browserReplayBusy ? (
                <Loader2 size={16} className={styles.spinIcon} />
              ) : (
                <Play size={16} />
              )}
            </button>
          </Tooltip>
        )}
        {isStreaming ? (
          <>
            <Tooltip title={isTeam ? t("chat.stopTeamHint") : t("chat.stop")}>
              <button
                className={`${styles.sendBtn} ${styles.cancelBtn}`}
                onClick={onCancel}
                type="button"
                aria-label={t("chat.stop", "Stop")}
              >
                <Square size={18} aria-hidden />
              </button>
            </Tooltip>
            {canSend && (
              <Tooltip title={isTeam ? t("chat.send") : t("chat.queue.action")}>
                <button
                  className={styles.sendBtn}
                  onClick={onSubmit}
                  disabled={disabled}
                  title={isTeam ? t("chat.send") : t("chat.queue.action")}
                  type="button"
                  aria-label={isTeam ? t("chat.send") : t("chat.queue.action")}
                >
                  {isTeam ? <Send size={18} /> : <ListPlus size={18} />}
                </button>
              </Tooltip>
            )}
          </>
        ) : (
          <button
            className={styles.sendBtn}
            onClick={onSubmit}
            disabled={!canSend}
            title={t("chat.send", "Send")}
            type="button"
          >
            <Send size={18} />
          </button>
        )}
      </div>
    </div>
  );
}
