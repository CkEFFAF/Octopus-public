import { stripThinkingTags } from "./chatAttachments";

/** Only public text is rendered. Reasoning/tool/system blocks are never displayed. */
export function publicText(content: unknown): string {
  if (typeof content === "string") return stripThinkingTags(content);
  if (!Array.isArray(content)) return "";
  return stripThinkingTags(
    content
      .filter(
        (block) => block?.type === "text" && typeof block.text === "string",
      )
      .map((block) => block.text)
      .join("\n"),
  );
}
