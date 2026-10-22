import {
  useState,
  useRef,
  useCallback,
  useEffect,
  useMemo,
  forwardRef,
  useImperativeHandle,
  type ReactNode,
} from "react";
import { useTranslation } from "react-i18next";
import { App } from "antd";

import { useIsMobile } from "../../../hooks/useIsMobile";
import {
  isPwaDisplay,
  needsComposerVisualViewportFix,
} from "../../../hooks/viewport";
import { useKeepInVisualViewport } from "../../../hooks/useKeepInVisualViewport";
import { useSlashCommands } from "../../../hooks/useSlashCommands";
import SlashCommandMenu from "./SlashCommandMenu";
import { agentChatApi } from "../../../api/modules/agentChat";
import type { ChatAttachment } from "../hooks/useChat";
import type { ResolvedModel } from "../../../api/types";
import type { KnowledgeBase } from "../../../api/modules/knowledgeBases";
import type { SkillSpec } from "../../Agent/Skills/useSkills";
import type { ChatAgentOption } from "./ExpertAgentAvatar";
import type { AgentSubagentSummary } from "../../../api/modules/subagents";
import MentionPickerMenu from "./MentionPickerMenu";
import ChatInputPreviewBar from "./ChatInputPreviewBar";
import ChatInputActionsRow from "./ChatInputActionsRow";
import { type WorkMode } from "../utils/workMode";
import {
  executionScope,
  setExecutionSelection,
  useExecutionSelection,
} from "../hooks/deviceTarget";
import ChatQueuedMessages from "./ChatQueuedMessages";
import { useVoiceInput } from "../../../hooks/useVoiceInput";
import { useChatAttachments } from "../hooks/useChatAttachments";
import { useSlashMentionInput } from "../hooks/useSlashMentionInput";
import { stripThinkingTags } from "../utils/chatAttachments";
import { isSlashCommandText } from "../utils/slashText";
import {
  ensureExpertMentions,
  expertMentionToken,
  toggleExpertMention,
} from "../utils/expertMention";
import {
  insertSkillSlash,
  materializeSkillSlashes,
  parseSkillSlugsInText,
  type SkillTokenRef,
} from "../utils/skillSlash";
import { useSkillDisplayName } from "../../Agent/Skills/skillDisplayNames";
import {
  consumePendingPrefillAttachments,
  readInputDraft,
  writeInputDraft,
} from "../hooks/chatStore";
import {
  buildComposerContext,
  resolveTurnModelRef,
} from "../utils/chatMessages";
import type {
  EnqueueChatItemInput,
  QueuedChatItem,
} from "../hooks/useChatMessageQueue";
import type { HitlSessionPolicy } from "../utils/hitlSessionPolicy";
import { useComposerResize } from "../hooks/useComposerResize";
import styles from "../index.module.less";
import {
  saveWithdrawnDraft,
  readWithdrawnDraft,
  takeWithdrawnDraft,
  subscribeWithdrawnDraft,
} from "../utils/withdrawnDraft";

/** Imperative handle exposed via ref for programmatic text injection. */
export interface ChatInputHandle {
  setPrefillText: (text: string) => void;
  setPrefillComposer: (text: string, attachments?: ChatAttachment[]) => void;
  focusComposer: () => void;
  mentionExpert: (name: string) => void;
  attachFiles: (files: File[]) => void;
}

interface ChatInputProps {
  footer?: ReactNode;
  onSend: (text: string, attachments?: ChatAttachment[]) => void;
  /** Queue a message while the current turn is still streaming. */
  onQueue?: (
    item: EnqueueChatItemInput,
  ) => "ok" | "empty" | "full" | Promise<"ok" | "empty" | "full">;
  /** Promote an already queued message into the active turn. */
  onSteerQueued?: (
    id: string,
    cancelTools?: boolean,
  ) => boolean | Promise<boolean>;
  onDismissQueued?: (id: string) => boolean | Promise<boolean>;
  queuedItems?: QueuedChatItem[];
  onReclaimQueued?: (
    id: string,
  ) => QueuedChatItem | null | Promise<QueuedChatItem | null>;
  onCancel: () => void;
  onNewChat: () => void;
  onUserInput?: () => void;
  browserRecording?: boolean;
  browserReplayBusy?: boolean;
  browserLastRecordingId?: string | null;
  onStartBrowserRecording?: () => void;
  onStopBrowserRecording?: () => void;
  onReplayBrowserRecording?: () => void;
  isStreaming: boolean;
  /** Team room: send immediately even while members (or the host) are still talking. */
  isTeam?: boolean;
  disabled?: boolean;
  /** Pre-fill the input with this text on mount (e.g. navigated from another page). */
  initialText?: string;
  /** Called when the composer is cleared after a successful send/queue. */
  onComposerCleared?: () => void;
  availableModels?: ResolvedModel[];
  selectedModel?: string | null;
  onModelChange?: (model: string | null) => void;
  reasoningMode?: "auto" | "enabled" | "disabled";
  reasoningEffort?: string | null;
  onReasoningChange?: (
    mode: "auto" | "enabled" | "disabled",
    effort: string | null,
  ) => void;
  conversationMode?: "ask" | "plan" | "craft";
  onConversationModeChange?: (mode: "ask" | "plan" | "craft") => void;
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
  availableAgents?: ChatAgentOption[];
  /**
   * Subset of experts the user can currently pick — only running ones
   * (stopped / failed experts would dispatch into an unloaded harness and
   * silently fail). Pass the same list as ``availableAgents`` if every
   * expert is guaranteed to be running.
   */
  availableExperts?: ChatAgentOption[];
  availableSubagents?: AgentSubagentSummary[];
  agentId?: string | null;
  threadId?: string | null;
  defaultModel?: string | null;
  contextUsedTokens?: number | null;
  contextMaxTokens?: number;
  onInspectContext?: () => void;
  deviceControl?: React.ReactNode;
  runtimePhase?: string;
}

const ChatInput = forwardRef<ChatInputHandle, ChatInputProps>(
  function ChatInput(
    {
      footer,
      onSend,
      onQueue,
      onSteerQueued,
      onDismissQueued,
      runtimePhase,
      queuedItems = [],
      onReclaimQueued,
      onCancel,
      onNewChat,
      onUserInput,
      browserRecording,
      browserReplayBusy,
      browserLastRecordingId,
      onStartBrowserRecording,
      onStopBrowserRecording,
      onReplayBrowserRecording,
      isStreaming,
      isTeam = false,
      disabled,
      initialText = "",
      onComposerCleared,
      availableModels,
      selectedModel,
      onModelChange,
      reasoningMode = "auto",
      reasoningEffort = null,
      onReasoningChange,
      conversationMode = "craft",
      onConversationModeChange,
      hitlPolicy,
      onHitlPolicyChange,
      availableConnectors,
      selectedConnectors = [],
      onConnectorsChange,
      availableKnowledgeBases,
      selectedKnowledgeBaseIds = [],
      onKnowledgeBaseIdsChange,
      availableSkills,
      availableAgents = [],
      // Default ``availableExperts`` to the full projection so older callers
      // (and tests) keep working. Production callers in ``Chat/index.tsx``
      // explicitly pass the filtered list — keep that explicit to avoid
      // accidentally re-surfacing stopped experts in the @-picker.
      availableExperts = availableAgents,
      availableSubagents = [],
      agentId,
      threadId,
      defaultModel,
      contextUsedTokens = null,
      contextMaxTokens = 128_000,
      onInspectContext,
      deviceControl,
    },
    ref,
  ) {
    const { t, i18n } = useTranslation();
    const scope = executionScope(agentId, threadId);
    const { workMode: selectedWorkMode } = useExecutionSelection(scope);
    const setSelectedWorkMode = (mode: WorkMode) =>
      setExecutionSelection(scope, { workMode: mode });
    const workMode: WorkMode =
      conversationMode === "craft"
        ? selectedWorkMode === "plan" || selectedWorkMode === "ask"
          ? "agentic"
          : selectedWorkMode
        : conversationMode;
    const { modal, message: antMessage } = App.useApp();
    const { commands: slashCommands, labelFor } = useSlashCommands("ui");
    const skillDisplayName = useSkillDisplayName();
    const isMobile = useIsMobile();
    const shellRef = useRef<HTMLDivElement>(null);
    const keepComposerInView =
      typeof window !== "undefined" &&
      !isPwaDisplay() &&
      (isMobile || needsComposerVisualViewportFix());
    useKeepInVisualViewport(shellRef, keepComposerInView);
    const [text, setText] = useState(
      () => initialText || readInputDraft(agentId, threadId),
    );
    const [polishing, setPolishing] = useState(false);
    const [reclaiming, setReclaiming] = useState(false);
    const reclaimPending = useRef(false);
    const composerMounted = useRef(true);
    useEffect(() => {
      composerMounted.current = true;
      return () => {
        composerMounted.current = false;
      };
    }, []);
    const composerDisabled = disabled || reclaiming;
    // Track whether the user has manually edited the text after a prefill.
    // Once they start editing, we must not overwrite their input with a new
    // initialText value (e.g. from a parent re-render or a stale effect).
    const userHasEditedRef = useRef(false);
    // After submit, ignore one re-application of this exact initialText value
    // (parent may still hold the prefill string in a ref across the next render).
    const ignoreInitialTextRef = useRef<string | null>(null);

    const setComposerText = useCallback((value: string) => {
      if (reclaimPending.current) return;
      userHasEditedRef.current = true;
      setText(value);
    }, []);

    const handleVoiceText = useCallback(
      (spoken: string) => {
        if (reclaimPending.current) return;
        setText((prev) => (prev.trim() ? `${prev.trim()} ${spoken}` : spoken));
        userHasEditedRef.current = true;
        onUserInput?.();
      },
      [onUserInput],
    );
    const {
      recording,
      transcribing,
      toggle: toggleVoice,
    } = useVoiceInput(handleVoiceText);
    const textareaRef = useRef<HTMLTextAreaElement>(null);
    const {
      attachments,
      uploading,
      dragOver,
      fileInputRef,
      handleFileSelect,
      handleFileChange,
      removeAttachment,
      clearAttachments,
      restoreAttachments,
      handlePaste,
      handleDragEnter,
      handleDragLeave,
      handleDragOver,
      handleDrop,
      processFiles,
    } = useChatAttachments(agentId);

    // Expose an imperative handle so the parent can push a new prefill without
    // triggering a prop change that would cause a re-render cascade.
    useImperativeHandle(
      ref,
      () => ({
        attachFiles: (files: File[]) => {
          if (reclaimPending.current) return;
          void processFiles(files);
        },
        mentionExpert: (name: string) => {
          if (reclaimPending.current) return;
          userHasEditedRef.current = true;
          setText(
            (previous) =>
              `${previous.trimEnd()}${
                previous.trim() ? " " : ""
              }${expertMentionToken(name)} `,
          );
          textareaRef.current?.focus();
        },
        setPrefillText: (newText: string) => {
          if (reclaimPending.current) return;
          userHasEditedRef.current = false;
          ignoreInitialTextRef.current = null;
          prevInitialTextRef.current = newText;
          setText(newText);
          setTimeout(() => {
            const el = textareaRef.current;
            if (el) {
              el.focus();
              el.setSelectionRange(el.value.length, el.value.length);
            }
          }, 50);
        },
        setPrefillComposer: (
          newText: string,
          nextAttachments?: ChatAttachment[],
        ) => {
          if (reclaimPending.current) return;
          userHasEditedRef.current = false;
          ignoreInitialTextRef.current = null;
          prevInitialTextRef.current = newText;
          setText(newText);
          if (nextAttachments && nextAttachments.length > 0) {
            restoreAttachments(
              nextAttachments.map((attachment) => ({ ...attachment })),
            );
          } else {
            clearAttachments();
          }
          setTimeout(() => {
            const el = textareaRef.current;
            if (el) {
              el.focus();
              el.setSelectionRange(el.value.length, el.value.length);
            }
          }, 50);
        },
        focusComposer: () => {
          const el = textareaRef.current;
          if (!el) return;
          el.focus();
          el.setSelectionRange(el.value.length, el.value.length);
        },
      }),
      [clearAttachments, restoreAttachments, processFiles],
    );

    // When the parent passes a non-empty initialText after mount (e.g. navigated
    // from cron-jobs), update the input value and move the cursor to the end.
    // Only fires when initialText actually changes AND the user hasn't started
    // editing yet (prevents overwriting mid-edit content).
    const prevInitialTextRef = useRef(initialText);
    const prevComposerKeyRef = useRef(`${agentId ?? ""}:${threadId ?? ""}`);
    useEffect(() => {
      if (
        ignoreInitialTextRef.current !== null &&
        initialText === ignoreInitialTextRef.current
      ) {
        // Stale post-submit prop — acknowledge without restoring cleared text.
        ignoreInitialTextRef.current = null;
        prevInitialTextRef.current = initialText;
        return;
      }
      if (ignoreInitialTextRef.current !== null) {
        // A different (or empty) prop arrived — stop ignoring.
        ignoreInitialTextRef.current = null;
      }
      if (
        initialText &&
        initialText !== prevInitialTextRef.current &&
        !userHasEditedRef.current
      ) {
        prevInitialTextRef.current = initialText;
        setText(initialText);
        // Focus the textarea so the user can immediately start editing
        setTimeout(() => {
          const el = textareaRef.current;
          if (el) {
            el.focus();
            el.setSelectionRange(el.value.length, el.value.length);
          }
        }, 50);
      }
    }, [initialText]);

    const restoreQueuedDraft = useCallback(
      (item: QueuedChatItem) => {
        userHasEditedRef.current = true;
        const ctx = item.composerContext;
        setText(
          ctx?.targetAgents?.length
            ? ensureExpertMentions(item.text, ctx.targetAgents, availableAgents)
            : item.text,
        );
        restoreAttachments(item.attachments ?? []);
        if (ctx) {
          onConnectorsChange?.(ctx.connectors ?? []);
          onKnowledgeBaseIdsChange?.(ctx.knowledgeBaseIds ?? []);
          if (ctx.model !== undefined) onModelChange?.(ctx.model);
          else if (item.modelRef !== undefined) onModelChange?.(item.modelRef);
          if (ctx.reasoningMode !== undefined)
            onReasoningChange?.(ctx.reasoningMode, ctx.reasoningEffort || null);
        } else if (item.modelRef !== undefined) onModelChange?.(item.modelRef);
      },
      [
        availableAgents,
        restoreAttachments,
        onConnectorsChange,
        onKnowledgeBaseIdsChange,
        onModelChange,
        onReasoningChange,
      ],
    );

    const recoveryPrompt = useRef<string | null>(null);
    const offerWithdrawnDraft = useCallback(
      (draftText: string, hasAttachments: boolean) => {
        const recovered = readWithdrawnDraft(agentId, threadId);
        if (!recovered) return;
        const identity = JSON.stringify([agentId, threadId, recovered.id]);
        if (recoveryPrompt.current === identity) return;
        const apply = () => {
          if (
            !composerMounted.current ||
            latestComposer.current.agentId !== agentId ||
            latestComposer.current.threadId !== threadId
          )
            return;
          const item = takeWithdrawnDraft(agentId, threadId);
          if (item) restoreQueuedDraft(item);
        };
        if (draftText.trim() || hasAttachments) {
          recoveryPrompt.current = identity;
          modal.confirm({
            title: t("chat.queue.reclaimOverwriteTitle"),
            content: t("chat.queue.reclaimOverwrite"),
            okText: t("common.confirm", "确认"),
            cancelText: t("common.cancel", "取消"),
            onOk: apply,
          });
        } else apply();
      },
      [agentId, threadId, restoreQueuedDraft, modal, t],
    );

    // Restore per-thread drafts and offer recovered withdrawals without replacing edits.
    useEffect(() => {
      const composerKey = `${agentId ?? ""}:${threadId ?? ""}`;
      const changed = composerKey !== prevComposerKeyRef.current;
      const targetText = changed
        ? readInputDraft(agentId, threadId)
        : latestComposer.current.text;
      if (changed) {
        prevComposerKeyRef.current = composerKey;
        recoveryPrompt.current = null;
        userHasEditedRef.current = false;
        ignoreInitialTextRef.current = null;
        prevInitialTextRef.current = "";
        setText(targetText);
        const pendingAttachments = consumePendingPrefillAttachments();
        if (pendingAttachments.length) restoreAttachments(pendingAttachments);
        else clearAttachments();
        offerWithdrawnDraft(targetText, pendingAttachments.length > 0);
      } else
        offerWithdrawnDraft(
          targetText,
          latestComposer.current.attachments.length > 0,
        );
    }, [
      agentId,
      threadId,
      clearAttachments,
      restoreAttachments,
      offerWithdrawnDraft,
    ]);

    // Persist draft while typing so leaving /chat and returning keeps content.
    useEffect(() => {
      if (!agentId) return;
      const timer = window.setTimeout(() => {
        writeInputDraft(agentId, threadId, text);
      }, 250);
      return () => window.clearTimeout(timer);
    }, [text, agentId, threadId]);
    const submissionPending = useRef(false);
    const latestComposer = useRef({ text, attachments, agentId, threadId });
    latestComposer.current = { text, attachments, agentId, threadId };
    useEffect(
      () =>
        subscribeWithdrawnDraft(agentId, threadId, () => {
          const draft = latestComposer.current;
          offerWithdrawnDraft(draft.text, draft.attachments.length > 0);
        }),
      [agentId, threadId, offerWithdrawnDraft],
    );
    const submitRef = useRef<() => void>(() => {});

    const {
      slashMenuOpen,
      slashMenuIndex,
      setSlashMenuIndex,
      mentionMenuOpen,
      mentionMenuIndex,
      setMentionMenuIndex,
      mentionQuery,
      mentionAgents,
      slashMenuFlat,
      slashMenuGroups,
      slashPickerGroups,
      slashMenuItems,
      mentionItems,
      filesLoading,
      filesError,
      runSlashCommand,
      matchSlashCommand,
      handleMentionSelect,
      handleSlashSelect,
      handleTextChange,
      handleKeyDown,
    } = useSlashMentionInput({
      text,
      setText: setComposerText,
      textareaRef,
      slashCommands,
      labelFor,
      locale: i18n.language,
      availableSkills,
      availableConnectors,
      availableExperts,
      availableSubagents,
      agentId,
      selectedConnectors,
      onConnectorsChange,
      onSend,
      onNewChat,
      onCancel,
      isStreaming,
      onSubmitRef: submitRef,
      enterToSend: !isMobile,
    });

    const skillTokenRefs = useMemo<SkillTokenRef[]>(
      () =>
        (availableSkills ?? []).map((skill) => ({
          slug: skill.slug,
          label: skillDisplayName(skill),
          emoji: skill.emoji,
        })),
      [availableSkills, skillDisplayName],
    );

    const insertSkillCommand = useCallback(
      (slug: string) => {
        userHasEditedRef.current = true;
        const ref =
          skillTokenRefs.find(
            (item) => item.slug.toLowerCase() === slug.toLowerCase(),
          ) ?? ({ slug } satisfies SkillTokenRef);
        const next = insertSkillSlash(text, ref);
        setText(next);
        requestAnimationFrame(() => {
          const el = textareaRef.current;
          if (!el) return;
          el.focus();
          el.setSelectionRange(next.length, next.length);
        });
      },
      [text, skillTokenRefs],
    );

    const selectedSkillSlugs = useMemo(
      () => parseSkillSlugsInText(text, skillTokenRefs),
      [text, skillTokenRefs],
    );

    const insertExpertMention = useCallback(
      (agent: ChatAgentOption) => {
        userHasEditedRef.current = true;
        const next = toggleExpertMention(text, agent.name);
        setText(next.text);
        requestAnimationFrame(() => {
          const el = textareaRef.current;
          if (!el) return;
          el.focus();
          el.setSelectionRange(next.cursor, next.cursor);
        });
      },
      [text],
    );

    const insertSubagentMention = useCallback(
      (subagent: AgentSubagentSummary) => {
        userHasEditedRef.current = true;
        const next = toggleExpertMention(text, subagent.slug);
        setText(next.text);
        requestAnimationFrame(() => {
          const el = textareaRef.current;
          if (!el) return;
          el.focus();
          el.setSelectionRange(next.cursor, next.cursor);
        });
      },
      [text],
    );

    const resetComposerAfterSubmit = useCallback(
      (_prevHeight: number, submittedText: string) => {
        setText("");
        writeInputDraft(agentId, threadId, "");
        clearAttachments();
        userHasEditedRef.current = false;
        // Parent may re-pass the same prefill as initialText on the next render
        // (skill-card / cron keep it in a ref). Ignore that exact value once.
        ignoreInitialTextRef.current = submittedText;
        prevInitialTextRef.current = initialText;
        onComposerCleared?.();
      },
      [agentId, threadId, clearAttachments, initialText, onComposerCleared],
    );

    const submitMessage = useCallback(async () => {
      const trimmed = text.trim();
      if (
        (!trimmed && attachments.length === 0) ||
        disabled ||
        reclaimPending.current
      )
        return;
      const rawText = materializeSkillSlashes(trimmed, skillTokenRefs).trim();
      const slashItem = matchSlashCommand(rawText);
      if (slashItem && slashItem.spec.client_action !== "none") {
        // Slash actions are never queued — run immediately or leave input alone.
        if (isStreaming) return;
        runSlashCommand(slashItem);
        return;
      }
      // Preserve server-handled slash commands verbatim. Prefixing a work-mode
      // instruction would stop the command parser from recognizing them.
      const wireText = rawText;
      const ta = textareaRef.current;
      const prevHeight = ta ? ta.getBoundingClientRect().height : 0;

      if (isStreaming && !isTeam) {
        if (!onQueue) return;
        if (submissionPending.current) return;
        submissionPending.current = true;
        let result: "ok" | "empty" | "full";
        try {
          result = await onQueue({
            text: wireText,
            conversationMode,
            hitlPolicy,
            attachments: attachments.length > 0 ? attachments : undefined,
            composerContext: buildComposerContext({
              skills: selectedSkillSlugs,
              connectors: selectedConnectors,
              knowledgeBaseIds: selectedKnowledgeBaseIds,
              selectedModel,
              reasoningMode,
              reasoningEffort,
            }),
            modelRef: resolveTurnModelRef(selectedModel, defaultModel),
          });
        } finally {
          submissionPending.current = false;
        }
        if (result === "full") {
          antMessage.warning(t("chat.queue.full"));
          return;
        }
        if (result === "empty") return;
        if (
          latestComposer.current.text === text &&
          latestComposer.current.attachments === attachments &&
          latestComposer.current.agentId === agentId &&
          latestComposer.current.threadId === threadId
        ) {
          resetComposerAfterSubmit(prevHeight, trimmed);
        }
        return;
      }

      onSend(wireText, attachments.length > 0 ? attachments : undefined);
      resetComposerAfterSubmit(prevHeight, trimmed);
    }, [
      text,
      attachments,
      onSend,
      onQueue,
      disabled,
      isStreaming,
      isTeam,
      matchSlashCommand,
      runSlashCommand,
      resetComposerAfterSubmit,
      selectedConnectors,
      selectedKnowledgeBaseIds,
      selectedSkillSlugs,
      skillTokenRefs,
      selectedModel,
      reasoningMode,
      reasoningEffort,
      defaultModel,
      workMode,
      conversationMode,
      hitlPolicy,
      antMessage,
      agentId,
      threadId,
      i18n.language,
      t,
    ]);

    submitRef.current = submitMessage;

    const handleReclaimQueued = useCallback(
      (id: string) => {
        if (
          !onReclaimQueued ||
          disabled ||
          uploading ||
          recording ||
          transcribing ||
          reclaimPending.current
        )
          return;
        const apply = async () => {
          if (reclaimPending.current) return;
          // The server may already have withdrawn this item when its response arrives.
          // Keep this draft stable until it can be restored without overwriting edits.
          reclaimPending.current = true;
          setReclaiming(true);
          try {
            const item = await onReclaimQueued(id);
            if (!item) return;
            if (
              !composerMounted.current ||
              latestComposer.current.agentId !== agentId ||
              latestComposer.current.threadId !== threadId
            ) {
              saveWithdrawnDraft(agentId, threadId, item);
              return;
            }
            writeInputDraft(agentId, threadId, item.text);
            restoreQueuedDraft(item);
            setTimeout(() => {
              const el = textareaRef.current;
              if (el) {
                el.focus();
                el.setSelectionRange(el.value.length, el.value.length);
              }
            }, 50);
          } catch {
            antMessage.error(t("chat.queue.withdrawFailed"));
          } finally {
            reclaimPending.current = false;
            setReclaiming(false);
          }
        };

        if (text.trim() || attachments.length > 0) {
          modal.confirm({
            title: t("chat.queue.reclaimOverwriteTitle"),
            content: t("chat.queue.reclaimOverwrite"),
            okText: t("common.confirm", "确认"),
            cancelText: t("common.cancel", "取消"),
            onOk: apply,
          });
          return;
        }
        apply();
      },
      [
        onReclaimQueued,
        agentId,
        threadId,
        disabled,
        uploading,
        recording,
        transcribing,
        modal,
        antMessage,
        text,
        attachments.length,
        t,
        restoreQueuedDraft,
      ],
    );

    // Pixel Avatar: listen for user input.
    useEffect(() => {
      if (onUserInput && text.length > 0) {
        onUserInput();
      }
    }, [text, onUserInput]);

    const handlePolish = useCallback(async () => {
      const draft = text.trim();
      if (!draft || !agentId || polishing || isStreaming || disabled) return;
      setPolishing(true);
      try {
        const result = await agentChatApi.polish(agentId, draft, selectedModel);
        const polished = stripThinkingTags(result.text?.trim() ?? "");
        if (!polished) {
          antMessage.error(t("chat.polish.emptyResult"));
          return;
        }
        userHasEditedRef.current = true;
        setText(polished);
        setTimeout(() => {
          const el = textareaRef.current;
          if (el) {
            el.focus();
            el.setSelectionRange(el.value.length, el.value.length);
          }
        }, 50);
      } catch (err: unknown) {
        antMessage.error(
          err instanceof Error ? err.message : t("chat.polish.failed"),
        );
      } finally {
        setPolishing(false);
      }
    }, [text, agentId, polishing, isStreaming, disabled, selectedModel, t]);

    const composerResize = useComposerResize(isMobile);

    const canSend = Boolean(
      (text.trim() || attachments.length > 0) && !disabled,
    );

    return (
      <div
        ref={shellRef}
        data-chat-composer
        className={`${styles.chatInput} ${dragOver ? styles.dropActive : ""}`}
        onDragEnter={handleDragEnter}
        onDragLeave={handleDragLeave}
        onDragOver={handleDragOver}
        onDrop={(event) => {
          if (reclaimPending.current) {
            event.preventDefault();
            return;
          }
          handleDrop(event);
        }}
      >
        {isStreaming && runtimePhase ? (
          <div className={styles.runtimePhase} role="status">
            {t(`chat.steer.phase.${runtimePhase}`, {
              defaultValue: runtimePhase,
            })}
          </div>
        ) : null}
        {onReclaimQueued && (
          <ChatQueuedMessages
            items={queuedItems}
            onReclaim={handleReclaimQueued}
            onSteer={isTeam ? undefined : onSteerQueued}
            onDismiss={onDismissQueued}
            canSteer={isStreaming && !composerDisabled}
            disabled={
              composerDisabled || uploading || recording || transcribing
            }
          />
        )}
        <div
          className={`${styles.inputWrapper} ${styles.resizableComposer}`}
          ref={composerResize.wrapperRef}
          style={{
            height: composerResize.height,
            minHeight: composerResize.minHeight,
          }}
        >
          <div
            role="separator"
            tabIndex={0}
            aria-orientation="horizontal"
            aria-label={t("chat.resizeComposer")}
            aria-valuemin={Math.round(composerResize.minHeight)}
            aria-valuemax={Math.round(composerResize.maxHeight)}
            aria-valuenow={Math.round(composerResize.height)}
            className={styles.composerResizeHandle}
            onPointerDown={composerResize.onPointerDown}
            onKeyDown={composerResize.onKeyDown}
          />
          <ChatInputPreviewBar
            attachments={attachments}
            uploading={uploading}
            selectedConnectors={selectedConnectors}
            availableConnectors={availableConnectors}
            availableKnowledgeBases={availableKnowledgeBases}
            onRemoveAttachment={(id) => {
              if (!reclaimPending.current) removeAttachment(id);
            }}
            onConnectorsChange={
              composerDisabled ? undefined : onConnectorsChange
            }
            selectedKnowledgeBaseIds={selectedKnowledgeBaseIds}
            onKnowledgeBaseIdsChange={
              composerDisabled ? undefined : onKnowledgeBaseIdsChange
            }
          />

          <div className={styles.inputRow} style={{ position: "relative" }}>
            <textarea
              ref={textareaRef}
              className={styles.textarea}
              value={text}
              onChange={(e) => {
                if (reclaimPending.current) return;
                userHasEditedRef.current = true;
                handleTextChange(e.target.value);
              }}
              onKeyDown={handleKeyDown}
              onPaste={handlePaste}
              placeholder={t(
                "chatWelcome.inputPlaceholder",
                "Message Octop...",
              )}
              rows={1}
              disabled={composerDisabled}
              enterKeyHint={isMobile ? "enter" : undefined}
            />
            {/*
            Slash badge (plan §14.5): octop's HarnessProcessor handles slash
            commands server-side. The composer doesn't intercept them — it
            just surfaces a small inline pill so the user sees they're
            issuing a command, not a regular message.
          */}
            {isSlashCommandText(text) && (
              <span
                data-testid="slash-badge"
                style={{
                  position: "absolute",
                  top: 6,
                  right: 8,
                  display: "inline-flex",
                  alignItems: "center",
                  gap: 4,
                  padding: "2px 8px",
                  background: "var(--fn-color-brand-bg)",
                  color: "var(--fn-color-brand)",
                  border: "1px solid var(--fn-color-brand)",
                  borderRadius: 999,
                  fontSize: 11,
                  fontWeight: 600,
                  lineHeight: "16px",
                  pointerEvents: "none",
                  userSelect: "none",
                  letterSpacing: 0.2,
                }}
              >
                /<span style={{ fontWeight: 500 }}>slash</span>
              </span>
            )}
          </div>

          {mentionMenuOpen && (
            <MentionPickerMenu
              items={mentionItems}
              query={mentionQuery}
              agents={mentionAgents}
              subagents={availableSubagents}
              filesLoading={filesLoading}
              filesError={filesError}
              activeIndex={mentionMenuIndex}
              onSelect={handleMentionSelect}
              onHover={setMentionMenuIndex}
            />
          )}

          {/* Slash command inline menu */}
          {slashMenuOpen && slashMenuFlat.length > 0 && (
            <div className={styles.slashMenu}>
              <SlashCommandMenu
                groups={slashMenuGroups}
                flatItems={slashMenuFlat}
                activeIndex={slashMenuIndex}
                disabled={isStreaming || disabled}
                variant="inline"
                itemsGridClassName={styles.slashMenuGrid}
                itemClassName={styles.slashMenuItem}
                activeClassName={styles.slashMenuItemActive}
                categoryClassName={styles.slashMenuCategory}
                labelClassName={styles.slashMenuLabel}
                cmdClassName={styles.slashMenuCmd}
                onSelect={handleSlashSelect}
                onHover={setSlashMenuIndex}
                footer={
                  <div className={styles.slashMenuHint}>
                    {t(
                      "slash.menuHint",
                      "↑↓ navigate · Enter confirm · Esc close",
                    )}
                  </div>
                }
              />
            </div>
          )}

          <ChatInputActionsRow
            isMobile={isMobile}
            isStreaming={isStreaming}
            isTeam={isTeam}
            disabled={composerDisabled}
            canSend={canSend}
            text={text}
            polishing={polishing}
            uploading={uploading}
            recording={recording}
            transcribing={transcribing}
            browserRecording={browserRecording}
            browserReplayBusy={browserReplayBusy}
            browserLastRecordingId={browserLastRecordingId}
            onStartBrowserRecording={onStartBrowserRecording}
            onStopBrowserRecording={onStopBrowserRecording}
            onReplayBrowserRecording={onReplayBrowserRecording}
            agentId={agentId}
            threadId={threadId}
            contextUsedTokens={contextUsedTokens}
            contextMaxTokens={contextMaxTokens}
            onInspectContext={onInspectContext}
            deviceControl={deviceControl}
            availableModels={availableModels}
            selectedModel={selectedModel}
            onModelChange={onModelChange}
            reasoningMode={reasoningMode}
            reasoningEffort={reasoningEffort}
            onReasoningChange={onReasoningChange}
            conversationMode={conversationMode}
            onConversationModeChange={onConversationModeChange}
            workMode={workMode}
            onWorkModeChange={setSelectedWorkMode}
            hitlPolicy={hitlPolicy}
            onHitlPolicyChange={onHitlPolicyChange}
            defaultModel={defaultModel}
            availableConnectors={availableConnectors}
            selectedConnectors={selectedConnectors}
            onConnectorsChange={onConnectorsChange}
            availableKnowledgeBases={availableKnowledgeBases}
            selectedKnowledgeBaseIds={selectedKnowledgeBaseIds}
            onKnowledgeBaseIdsChange={onKnowledgeBaseIdsChange}
            availableSkills={availableSkills}
            onInsertSkillCommand={insertSkillCommand}
            availableExperts={availableExperts.filter(
              (a) => a.agent_id !== agentId,
            )}
            onInsertExpertMention={insertExpertMention}
            availableSubagents={availableSubagents}
            onInsertSubagentMention={insertSubagentMention}
            slashPickerGroups={slashPickerGroups}
            slashMenuItems={slashMenuItems}
            onSlashShortcutSelect={handleSlashSelect}
            onFileSelect={handleFileSelect}
            onNewChat={onNewChat}
            onPolish={() => void handlePolish()}
            onToggleVoice={() => toggleVoice()}
            onCancel={onCancel}
            onSubmit={submitMessage}
          />

          <input
            ref={fileInputRef}
            type="file"
            disabled={composerDisabled}
            multiple
            style={{ display: "none" }}
            onChange={handleFileChange}
          />
        </div>
        {footer ? <div className={styles.chatUsageFooter}>{footer}</div> : null}
      </div>
    );
  },
);

export default ChatInput;
