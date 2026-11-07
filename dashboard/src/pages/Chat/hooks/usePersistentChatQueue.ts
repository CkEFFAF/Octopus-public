import { useCallback, useEffect, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
  chatInputsApi,
  type ChatInputSnapshot,
} from "../../../api/modules/chatInputs";
import { message } from "@/utils/antdMessage";
import { generateId } from "../../../utils/messageParser";
import { isBridgeAgentId } from "../../../utils/remoteExpert";
import { buildUserMessageContent } from "../utils/chatAttachments";
import type {
  EnqueueChatItemInput,
  QueuedChatItem,
} from "./useChatMessageQueue";
import {
  executionScope,
  getExecutionSelection,
  executionSelectionReady,
} from "./deviceTarget";

export function usePersistentChatQueue({
  agentId,
  threadId,
  enabled = true,
  displayedUserMessageIds,
}: {
  agentId?: string | null;
  threadId?: string | null;
  enabled?: boolean;
  displayedUserMessageIds?: ReadonlySet<string>;
}) {
  const { t } = useTranslation();
  const active = Boolean(
    enabled && agentId && threadId && !isBridgeAgentId(agentId),
  );
  const key = JSON.stringify([agentId, threadId]);
  const [state, setState] = useState<{
    key: string;
    data: ChatInputSnapshot<QueuedChatItem>;
  } | null>(null);
  const requestIds = useRef(new Map<string, string>());
  const requestTimes = useRef(new Map<string, number>());
  const requestRuns = useRef(new Map<string, string>());
  const aliveKey = useRef(key);
  aliveKey.current = key;
  const refresh = useCallback(async () => {
    if (!active || !agentId || !threadId) return null;
    const data = await chatInputsApi.list<QueuedChatItem>(agentId, threadId);
    if (aliveKey.current === key) setState({ key, data });
    return data;
  }, [active, agentId, threadId, key]);
  useEffect(() => {
    if (!active || !agentId || !threadId) return;
    let stopped = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const poll = async () => {
      try {
        await refresh();
      } catch {
        /* Keep the last acknowledged server state during a network drop. */
      }
      if (!stopped) timer = setTimeout(poll, 1500);
    };
    void poll();
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  }, [active, agentId, threadId, refresh]);
  const data = state?.key === key ? state.data : null;
  const items: QueuedChatItem[] = (data?.inputs ?? [])
    .filter(
      (row) =>
        row.status !== "dispatching" ||
        !displayedUserMessageIds?.has(row.payload.command_id),
    )
    .filter((row) =>
      [
        "queued",
        "dispatching",
        "requested",
        "accepted",
        "unknown",
        "failed",
        "rejected",
      ].includes(row.status),
    )
    .map((row) => ({
      ...(row.payload.snapshot ?? {
        text: row.payload.text ?? "",
        id: row.payload.command_id,
        createdAt: row.created_at * 1000,
      }),
      id: row.payload.command_id,
      status:
        row.status === "accepted" && row.payload.cancel_tools
          ? "interrupting"
          : row.status,
    }));
  const stableId = (fingerprint: string) => {
    let id = requestIds.current.get(fingerprint);
    if (!id) {
      id = generateId();
      requestIds.current.set(fingerprint, id);
      requestTimes.current.set(id, Date.now());
    }
    return id;
  };
  const enqueue = async (
    input: EnqueueChatItemInput,
    continueRunId?: string,
  ): Promise<"ok" | "empty" | "full"> => {
    if (
      !agentId ||
      !threadId ||
      (!input.text.trim() && !input.attachments?.length)
    )
      return "empty";
    const scope = executionScope(agentId, threadId);
    if (!executionSelectionReady(scope, threadId)) {
      message.error(t("devices.sessionSelectionUnavailable"));
      return "empty";
    }
    const selection = { ...getExecutionSelection(scope) };
    const fingerprint = JSON.stringify([key, input, selection]);
    const recovering = requestIds.current.has(fingerprint);
    const id = stableId(fingerprint);
    if (!recovering && continueRunId)
      requestRuns.current.set(id, continueRunId);
    const snapshot: QueuedChatItem = {
      ...input,
      ...selection,
      id,
      text: input.text.trim(),
      createdAt: requestTimes.current.get(id) ?? Date.now(),
      executionSelection: { ...selection, scope },
    };
    const context = input.composerContext;
    const mode =
      input.conversationMode ??
      (selection.workMode === "ask" || selection.workMode === "plan"
        ? selection.workMode
        : "craft");
    const turn = {
      type: "user_turn",
      thread_id: threadId,
      text: snapshot.text,
      messages: [
        {
          role: "user",
          content: buildUserMessageContent(snapshot.text, snapshot.attachments),
        },
      ],
      model: input.modelRef,
      mcp_servers: context?.connectors ?? [],
      knowledge_base_ids: context?.knowledgeBaseIds ?? [],
      skills: context?.skills,
      target_agent_ids: context?.targetAgents,
      reasoning_mode: context?.reasoningMode,
      reasoning_effort: context?.reasoningEffort,
      conversation_mode: mode,
      hitl_policy: input.hitlPolicy,
      ...(selection.deviceId === "@local"
        ? { target_kind: "local" }
        : { target_kind: "device", device_id: selection.deviceId }),
      working_dir: selection.workingDir,
      work_mode: selection.workMode,
    };
    try {
      if (recovering) {
        const recovered = await refresh();
        const prior = recovered?.inputs.find(
          (row) => row.payload.command_id === id,
        );
        if (prior) {
          if (
            [
              "queued",
              "dispatching",
              "accepted",
              "applied",
              "completed",
            ].includes(prior.status)
          ) {
            requestIds.current.delete(fingerprint);
            requestTimes.current.delete(id);
            requestRuns.current.delete(id);
            return "ok";
          }
          message.error(t("chat.steer.status.unknown"));
          return "empty";
        }
      }
      const receipt = await chatInputsApi.queue(
        agentId,
        threadId,
        id,
        snapshot,
        turn,
        requestRuns.current.get(id),
      );
      if (
        continueRunId &&
        !["queued", "dispatching", "accepted", "applied", "completed"].includes(
          receipt.status,
        )
      ) {
        message.error(t("chat.steer.failed"));
        return "empty";
      }
      requestIds.current.delete(fingerprint);
      requestTimes.current.delete(id);
      requestRuns.current.delete(id);
      await refresh().catch(() => null);
      return "ok";
    } catch (error) {
      if (String(error).includes("queue_full")) return "full";
      if (String(error).includes("steering_image_model_unsupported")) {
        message.error(t("chat.flow.imageModelUnsupported"));
        return "empty";
      }
      if (
        String(error).includes("RESOURCE_VERSION_CHANGED") ||
        String(error).includes("RESOURCE_UNAVAILABLE")
      ) {
        message.error(t("chat.flow.attachmentChanged"));
        return "empty";
      }
      message.error(t("chat.queue.flushFailed"));
      return "empty";
    }
  };
  const remove = async (id: string) => {
    if (!agentId || !threadId) return false;
    try {
      await chatInputsApi.withdraw(agentId, threadId, id);
      await refresh().catch(() => null);
      return true;
    } catch {
      message.error(t("chat.queue.withdrawFailed"));
      await refresh().catch(() => null);
      return false;
    }
  };
  const reclaim = async (id: string): Promise<QueuedChatItem | null> => {
    const item = items.find((row) => row.id === id);
    return item && (await remove(id)) ? item : null;
  };
  const dismiss = async (id: string): Promise<boolean> => {
    if (!agentId || !threadId) return false;
    try {
      await chatInputsApi.dismiss(agentId, threadId, id);
      await refresh().catch(() => null);
      return true;
    } catch {
      message.error(t("chat.queue.dismissFailed"));
      return false;
    }
  };
  const promote = async (id: string, cancelTools = false): Promise<boolean> => {
    if (!agentId || !threadId) return false;
    try {
      const current = await refresh();
      const prior = current?.inputs.find(
        (row) => row.payload.command_id === id,
      );
      if (
        prior?.kind === "chat_steer" &&
        ["accepted", "applied"].includes(prior.status)
      ) {
        return true;
      }
      if (!current?.runtime || !current.capabilities.steer) {
        message.info(t("chat.steer.unavailable"));
        return false;
      }
      const receipt = await chatInputsApi.promote(
        agentId,
        threadId,
        id,
        current.runtime.run_id,
        cancelTools,
      );
      await refresh().catch(() => null);
      if (!["accepted", "applied"].includes(receipt.status)) {
        message.error(t("chat.steer.failed"));
        return false;
      }
      message.info(
        t(cancelTools ? "chat.steer.interrupting" : "chat.steer.waiting"),
      );
      return true;
    } catch {
      await refresh().catch(() => null);
      message.error(t("chat.steer.promoteFailed"));
      return false;
    }
  };
  const steer = async (input: EnqueueChatItemInput): Promise<boolean> => {
    if (!agentId || !threadId) return false;
    if (input.attachments?.length) {
      try {
        const current = data?.runtime ? data : await refresh();
        return (await enqueue(input, current?.runtime?.run_id)) === "ok";
      } catch {
        message.error(t("chat.steer.failed"));
        return false;
      }
    }
    const fingerprint = JSON.stringify([key, "steer", input.text]);
    const id = stableId(fingerprint);
    try {
      const current = await refresh();
      const prior = current?.inputs.find(
        (row) => row.kind === "chat_steer" && row.payload.command_id === id,
      );
      if (prior && ["accepted", "applied"].includes(prior.status)) {
        requestIds.current.delete(fingerprint);
        requestTimes.current.delete(id);
        return true;
      }
      if (
        prior &&
        [
          "unknown",
          "failed",
          "rejected",
          "inactive",
          "stale_run",
          "busy",
          "conflict",
        ].includes(prior.status)
      ) {
        requestIds.current.delete(fingerprint);
        requestTimes.current.delete(id);
        message.error(
          t(`chat.steer.status.${prior.status}`, {
            defaultValue: t("chat.steer.failed"),
          }),
        );
        return false;
      }
      if (!current?.runtime) {
        message.info(t("chat.steer.unavailable"));
        return false;
      }
      const receipt = await chatInputsApi.steer(
        agentId,
        threadId,
        id,
        current.runtime.run_id,
        input.text,
      );
      if (!["accepted", "applied"].includes(receipt.status)) {
        requestIds.current.delete(fingerprint);
        requestTimes.current.delete(id);
        message.error(
          t(`chat.steer.status.${receipt.status}`, {
            defaultValue: t("chat.steer.failed"),
          }),
        );
        return false;
      }
      requestIds.current.delete(fingerprint);
      requestTimes.current.delete(id);
      message.info(t("chat.steer.waiting"));
      await refresh().catch(() => null);
      return true;
    } catch {
      message.error(t("chat.steer.failed"));
      return false;
    }
  };
  // Navigating to a new chat must not withdraw acknowledged work in the previous one.
  const clear = () => undefined;
  return {
    enabled: active,
    items,
    enqueue,
    remove,
    reclaim,
    dismiss,
    promote,
    clear,
    steer,
    runtime: data?.runtime,
  };
}
