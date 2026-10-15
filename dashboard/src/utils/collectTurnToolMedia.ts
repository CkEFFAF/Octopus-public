import type { ChatMessage } from "../pages/Chat/hooks/useChat";
import type { AssistantTurnSplit } from "../pages/Chat/utils/messageContent";
import {
  collectToolMediaFromToolData,
  type ToolMediaItem,
} from "./toolMediaBlocks";

export type TurnToolMedia = {
  images: ToolMediaItem[];
  videos: ToolMediaItem[];
  files: Array<{ url: string; filename?: string }>;
};

// Messages are immutable: a changed output/attachment gets a new message.
// Share parsing between the turn media strip and the workspace file detector.
const messageMediaCache = new WeakMap<
  ChatMessage,
  Map<string | null, TurnToolMedia>
>();

export function collectTurnToolMedia(
  split: AssistantTurnSplit,
  agentId?: string | null,
): TurnToolMedia {
  const images: ToolMediaItem[] = [];
  const videos: ToolMediaItem[] = [];
  const files: Array<{ url: string; filename?: string }> = [];

  for (const msg of split?.tools ?? []) {
    const owner = msg.speakerAgentId?.trim() || agentId;
    const batch = collectMessageToolMedia(msg, owner);
    images.push(...batch.images);
    videos.push(...batch.videos);
    files.push(...batch.files);
  }

  return { images, videos, files };
}

export function collectMessageToolMedia(
  message: ChatMessage,
  agentId?: string | null,
): TurnToolMedia {
  const owner = agentId ?? null;
  const cached = messageMediaCache.get(message)?.get(owner);
  if (cached) return cached;
  const media = collectToolMediaFromToolData(
    message.toolData,
    agentId,
    message.attachments,
  );
  let byOwner = messageMediaCache.get(message);
  if (!byOwner) {
    byOwner = new Map();
    messageMediaCache.set(message, byOwner);
  }
  byOwner.set(owner, media);
  return media;
}
