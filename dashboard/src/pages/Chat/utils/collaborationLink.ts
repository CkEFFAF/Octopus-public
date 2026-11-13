/** Read a child conversation only from structured server tool metadata. */
export function collaborationThreadId(artifact: unknown): string | undefined {
  if (!artifact || typeof artifact !== "object") return undefined;
  const id = (artifact as Record<string, unknown>).collaboration_thread_id;
  return typeof id === "string" && id.trim() ? id.trim() : undefined;
}
