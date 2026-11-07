import type { ChatAttachment } from "../pages/Chat/hooks/sseHelpers";
import { inferKindFromNameAndMime } from "../pages/Chat/utils/chatAttachments";

/** Convert server-verified attachment metadata consistently in live and saved messages. */
export function inboundAttachments(raw: unknown): ChatAttachment[] {
  if (!Array.isArray(raw)) return [];
  return raw.flatMap((value) => {
    if (!value || typeof value !== "object") return [];
    const row = value as Record<string, unknown>;
    const workspacePath =
      typeof row.workspace_path === "string" ? row.workspace_path : "";
    if (!workspacePath) return [];
    const filename = typeof row.filename === "string" ? row.filename : "";
    const mediaType = typeof row.media_type === "string" ? row.media_type : "";
    const hint =
      row.kind === "image" || row.kind === "audio" || row.kind === "video"
        ? row.kind
        : "file";
    return [
      {
        url: "",
        filename,
        workspacePath,
        kind: inferKindFromNameAndMime(mediaType, filename, hint),
        mediaType: mediaType || undefined,
        ...(typeof row.resource_id === "string"
          ? { resourceId: row.resource_id }
          : {}),
        ...(typeof row.version === "string" ? { version: row.version } : {}),
      },
    ];
  });
}
