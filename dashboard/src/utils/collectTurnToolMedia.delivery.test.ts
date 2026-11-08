import { expect, it } from "vitest";
import { collectTurnToolMedia } from "./collectTurnToolMedia";
import { splitAssistantTurn } from "../pages/Chat/utils/messageContent";
import { parseStructuredToolOutput } from "./toolMediaBlocks";
import type { ChatMessage } from "../pages/Chat/hooks/useChat";
const tool = (id: string, path: string): ChatMessage => ({
  id,
  role: "assistant",
  content: "",
  timestamp: 1,
  toolData: { name: "send_file", output: "" },
  attachments: [
    {
      kind: "file",
      filename: "result.PNG",
      url:
        "/api/agents/main/workspace/download?path=" + encodeURIComponent(path),
    },
  ],
});
it("previews image files and deduplicates canonical paths across tool calls", () => {
  const result = collectTurnToolMedia(
    splitAssistantTurn([
      tool("a", "/outbound/chart.png"),
      tool("b", "outbound/chart.png"),
    ]),
    "main",
  );
  expect(result.images).toHaveLength(1);
  expect(result.files).toEqual([]);
  expect(result.images[0].url).toContain("path=outbound%2Fchart.png");
});
it("keeps distinct files with the same display name", () => {
  expect(
    collectTurnToolMedia(
      splitAssistantTurn([
        tool("a", "outbound/first.png"),
        tool("b", "outbound/second.png"),
      ]),
      "main",
    ).images,
  ).toHaveLength(2);
});
it("does not present image-shaped payloads from a failed file delivery", () => {
  const failed = tool("failed", "outbound/missing.png");
  failed.toolData!.errorCode = "tool_error";
  const result = collectTurnToolMedia(splitAssistantTurn([failed]), "main");
  expect(result.images).toEqual([]);
  expect(result.files).toEqual([]);
});
it("renders a published send through its immutable resource rather than a guessed device path", () => {
  const published = tool("published", "outbound/report.png");
  published.toolData = {
    name: "send_file_to_user",
    arguments: JSON.stringify({ file_path: "/gpu/report.png" }),
    output: JSON.stringify({
      status: "published",
      resource_id: "res_verified",
      version: "digest",
    }),
  };
  expect(
    collectTurnToolMedia(splitAssistantTurn([published]), "main").images,
  ).toEqual([]);
});
it("recognizes an image MIME type in a file-shaped tool result", () => {
  const result = parseStructuredToolOutput(
    JSON.stringify([
      {
        type: "file",
        filename: "result",
        media_type: "image/png",
        path: "outbound/chart.png",
      },
    ]),
    "main",
  );
  expect(result.images).toHaveLength(1);
  expect(result.files).toEqual([]);
  expect(result.images[0].url).toContain("/api/agents/main/");
});
