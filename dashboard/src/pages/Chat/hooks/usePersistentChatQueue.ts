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
}: {
  agentId?: string | null;
  threadId?: string | null;
  enabled?: boolean;
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
      status: row.status,
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
    const id = stableId(fingerprint);
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
      await chatInputsApi.queue(agentId, threadId, id, snapshot, turn);
      requestIds.current.delete(fingerprint);
      requestTimes.current.delete(id);
      await refresh().catch(() => null);
      return "ok";
    } catch (error) {
      if (String(error).includes("queue_full")) return "full";
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
  const steer = async (input: EnqueueChatItemInput): Promise<boolean> => {
    if (!agentId || !threadId) return false;
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
    clear,
    steer,
    runtime: data?.runtime,
  };
}
