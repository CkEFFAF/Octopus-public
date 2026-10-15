import { useMemo, useRef } from "react";
import { workspacePathFromAccessUrl } from "../../../utils/toolMediaBlocks";
import { collectMessageToolMedia } from "../../../utils/collectTurnToolMedia";
import { isWriteToolName } from "../constants";
import {
  canonicalizeDockFilePath,
  dedupeDockFilePaths,
  normalizeDockFilePath,
} from "../utils/dockFilePath";
import type { ChatMessage } from "./useChat";

/**
 * Candidate JSON keys that may carry a workspace file path.
 * Harness tool schemas differ across versions, so we accept several names.
 */
const PATH_KEYS = [
  "path",
  "file_path",
  "filepath",
  "filename",
  "dest",
  "target_path",
  "output_path",
  "source",
] as const;

/** A conservative file-name suffix used as a last-resort path fallback. */
const PATH_EXT_RE = /\.[A-Za-z][A-Za-z0-9._+-]{0,11}$/;

const messagePathsCache = new WeakMap<
  ChatMessage,
  Map<string | null, string[]>
>();

function pickPathFromObject(parsed: Record<string, unknown>): string {
  for (const key of PATH_KEYS) {
    const value = parsed[key];
    if (typeof value === "string" && value.trim()) return value.trim();
  }
  return "";
}

/** Reject version tokens (``1.0.2``) and built-in skill docs from the list. */
function isDockListablePath(path: string): boolean {
  const posix = path.replace(/\\/g, "/");
  if (!posix) return false;
  if (/(^|\/)_builtin_skills(\/|$)/i.test(posix)) return false;
  const base = posix.split("/").filter(Boolean).pop() || posix;
  if (/^[\d.]+$/.test(base)) return false;
  if (!PATH_EXT_RE.test(base)) return false;
  return true;
}

/**
 * Read a path-like key from tool arguments (object or JSON string).
 * Does not scan free text — that is a last-resort fallback.
 */
function pathFromStructuredArgs(raw: unknown): string {
  if (raw === null || raw === undefined) return "";
  if (typeof raw === "object") {
    return pickPathFromObject(raw as Record<string, unknown>);
  }
  if (typeof raw === "string") {
    const s = raw.trim();
    if (!s) return "";
    try {
      const parsed = JSON.parse(s) as Record<string, unknown>;
      if (parsed && typeof parsed === "object") {
        return pickPathFromObject(parsed);
      }
    } catch {
      return "";
    }
  }
  return "";
}

/**
 * Scan free text (tool ``output``, non-JSON arguments) for a path. Prefers
 * the on-disk workspace absolute path the harness reports, then any
 * file-name-ish token.
 */
function pathFromText(text: string): string {
  if (!text) return "";
  // Prefer full absolute path ending at ``/.octop/agents/…`` (keep ``/home/…``).
  const absMatch = /\/\.octop\/agents\/[^\s"'<>]+/i.exec(text);
  if (absMatch) {
    let start = absMatch.index;
    // Read preceding /path segments once. A repeated optional prefix in an
    // unanchored regex retries every slash when large tool output has no match.
    while (start > 0) {
      let segmentStart = start;
      while (segmentStart > 0 && /[\w.-]/.test(text[segmentStart - 1])) {
        segmentStart--;
      }
      if (segmentStart === start || text[segmentStart - 1] !== "/") break;
      start = segmentStart - 1;
    }
    return text.slice(start, absMatch.index + absMatch[0].length);
  }
  const outbound = text.match(
    /(?:^|[\s"'`])((?:outbound|inbound)\/[^\s"'<>]+)/i,
  );
  if (outbound) return outbound[1];
  const relMatch = text.match(
    /(?:^|\s)((?:generated|outbound|inbound)\/[^\s"'<>]+)/i,
  );
  if (relMatch) return relMatch[1];
  // Split candidates before checking path/suffix. Two overlapping greedy
  // ranges around '/' backtrack quadratically on long slash-heavy logs.
  for (const match of text.matchAll(/(?:^|\s)([^\s"'<>]+)(?=\s|$)/g)) {
    const candidate = match[1];
    const slash = candidate.indexOf("/", 1);
    if (
      slash < 1 ||
      !/^.+\.[A-Za-z][A-Za-z0-9._+-]{0,11}$/.test(candidate.slice(slash + 1))
    ) {
      continue;
    }
    return isDockListablePath(candidate) ? candidate : "";
  }
  return "";
}

function extractWriteToolPath(message: ChatMessage): string | null {
  const name = message.toolData?.name ?? "";
  if (!isWriteToolName(name)) return null;

  const fromArgs = pathFromStructuredArgs(message.toolData?.arguments);
  if (fromArgs) return fromArgs;

  const fallbacks = [
    message.toolData?.arguments,
    message.toolData?.output,
    message.content,
  ].filter(
    (value): value is string =>
      typeof value === "string" && value.trim().length > 0,
  );
  for (const raw of fallbacks) {
    const found = pathFromText(raw);
    if (found) return found;
  }
  return null;
}

function addPath(
  paths: string[],
  path: string | null,
  agentId?: string | null,
) {
  const key = path ? canonicalizeDockFilePath(path, agentId) : "";
  if (!key || !isDockListablePath(key)) return;
  // Keep the original (richer) path for folder display; dedupe collapses later.
  paths.push(normalizeDockFilePath(path!) || key);
}

/**
 * Collect workspace file paths from the active thread so the docked file
 * panel can switch among written / previewable / attached files together.
 */
export function useChatFileDetection(
  _activeThreadId: string | null,
  messages: ChatMessage[],
  agentId?: string | null,
) {
  const previousPathsRef = useRef<string[]>([]);
  const filePaths = useMemo(() => {
    const next = collectChatFilePaths(messages, agentId);
    const previous = previousPathsRef.current;
    if (
      next.length === previous.length &&
      next.every((path, index) => path === previous[index])
    ) {
      return previous;
    }
    previousPathsRef.current = next;
    return next;
  }, [messages, agentId]);

  return { filePaths };
}

/** Collect unique workspace file paths from a slice of chat messages. */
export function collectChatFilePaths(
  messages: ChatMessage[],
  agentId?: string | null,
): string[] {
  const paths: string[] = [];
  for (const m of messages) {
    const ownerId = m.speakerAgentId?.trim() || agentId;
    paths.push(...collectMessageFilePaths(m, ownerId));
  }
  return dedupeDockFilePaths(paths, agentId);
}

function collectMessageFilePaths(
  m: ChatMessage,
  ownerId?: string | null,
): string[] {
  const owner = ownerId ?? null;
  const cached = messagePathsCache.get(m)?.get(owner);
  if (cached) return cached;
  const paths: string[] = [];
  addPath(paths, extractWriteToolPath(m), ownerId);
  for (const path of m.editedFiles ?? []) {
    addPath(paths, path, ownerId);
  }
  for (const att of m.attachments ?? []) {
    if (att.workspacePath) {
      addPath(paths, att.workspacePath, ownerId);
    } else if (att.url) {
      addPath(paths, workspacePathFromAccessUrl(att.url) ?? null, ownerId);
    }
  }
  const media = collectMessageToolMedia(m, ownerId);
  for (const file of media.files) {
    addPath(paths, workspacePathFromAccessUrl(file.url) ?? null, ownerId);
  }
  for (const img of media.images) {
    addPath(paths, workspacePathFromAccessUrl(img.url) ?? null, ownerId);
  }
  for (const video of media.videos) {
    addPath(paths, workspacePathFromAccessUrl(video.url) ?? null, ownerId);
  }
  let byOwner = messagePathsCache.get(m);
  if (!byOwner) {
    byOwner = new Map();
    messagePathsCache.set(m, byOwner);
  }
  byOwner.set(owner, paths);
  return paths;
}
