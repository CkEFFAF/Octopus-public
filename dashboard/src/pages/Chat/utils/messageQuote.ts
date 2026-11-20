import { octopThreadsApi } from "../../../api/modules/octopThreads";
import { extractContentBlocks } from "../../../utils/messageParser";
import type { ChatMessage } from "../hooks/useChat";
import { splitAssistantTurn } from "./messageContent";

export type MessageQuoteHandler = (
  message: ChatMessage,
  sourceMessages?: ChatMessage[],
) => void;

export function prependMessageQuote(
  draft: string,
  content: string,
  label: string,
): string {
  const quoted = content.replace(/\r\n?/g, "\n").trim();
  if (!quoted) return draft;
  return `> ${label}\n${quoted
    .split("\n")
    .map((line) => `> ${line}`)
    .join("\n")}\n\n${draft}`;
}

async function completeMessage(message: ChatMessage): Promise<ChatMessage> {
  const detail = message.historyDetail;
  if (!detail) return message;
  const page = await octopThreadsApi.history(detail.agentId, detail.threadId, {
    limit: 1,
    cursor: detail.cursor,
  });
  const full = page.messages[0];
  if (
    page.thread_id !== detail.threadId ||
    page.history_loading ||
    page.detail_cursor !== detail.cursor ||
    full?.role !== message.role
  ) {
    throw new Error("Invalid quoted history message");
  }
  const content =
    typeof full.content === "string"
      ? full.content
      : (extractContentBlocks(full.content) ?? [])
          .filter((block) => block.type === "text")
          .map((block) => block.content)
          .join("");
  return {
    ...message,
    content,
    contentBlocks: undefined,
    historyDetail: undefined,
  };
}

export async function resolveMessageQuote(
  message: ChatMessage,
  sourceMessages?: ChatMessage[],
): Promise<string> {
  if (sourceMessages?.some((source) => source.historyDetail)) {
    const complete = await Promise.all(sourceMessages.map(completeMessage));
    return splitAssistantTurn(complete).answerMessage?.content ?? "";
  }
  return (await completeMessage(message)).content;
}
