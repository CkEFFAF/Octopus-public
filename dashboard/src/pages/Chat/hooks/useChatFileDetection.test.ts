import { renderHook } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { ChatMessage } from "./sseHelpers";
import {
  collectChatFilePaths,
  useChatFileDetection,
} from "./useChatFileDetection";

function toolMsg(partial: {
  name: string;
  arguments: string;
  output?: string;
  content?: string;
}): ChatMessage {
  return {
    id: "t1",
    role: "assistant",
    content: partial.content ?? "",
    timestamp: 1,
    toolData: {
      name: partial.name,
      arguments: partial.arguments,
      output: partial.output,
    },
  };
}

describe("collectChatFilePaths", () => {
  it("prefers a structured args path over result text", () => {
    const paths = collectChatFilePaths([
      toolMsg({
        name: "write_file",
        arguments: JSON.stringify({ path: "generated/report.pptx" }),
        output: "Wrote outbound/screenshots/harness.png",
        content: "Also mentioned outbound/screenshots/harness.png",
      }),
    ]);
    expect(paths).toEqual(["generated/report.pptx"]);
  });

  it("scans tool output when args have no path", () => {
    const paths = collectChatFilePaths([
      toolMsg({
        name: "write_file",
        arguments: JSON.stringify({ content: "hello" }),
        output: "Wrote /home/wally/.octop/agents/A1/outbound/notes.md",
      }),
    ]);
    expect(paths).toEqual(["/home/wally/.octop/agents/A1/outbound/notes.md"]);
  });

  it.each([
    [
      "Saved /srv/team-1/.octop/agents/A1/report.md",
      "/srv/team-1/.octop/agents/A1/report.md",
    ],
    [
      "Saved /srv//team/.octop/agents/A1/report.md",
      "/team/.octop/agents/A1/report.md",
    ],
    ["Saved generated/report.pdf", "generated/report.pdf"],
    ["Saved local/report.tar.gz", "local/report.tar.gz"],
    ["Saved local/.hidden.txt", "local/.hidden.txt"],
    ["Ignore local/.txt", null],
    ["Ignore local/.txt.", null],
    ["Ignore local/_builtin_skills/readme.md", null],
  ])("preserves free-text path extraction for %s", (output, expected) => {
    expect(
      collectChatFilePaths(
        [toolMsg({ name: "write_file", arguments: "{}", output: output! })],
        "A1",
      ),
    ).toEqual(expected ? [expected] : []);
  });

  it("handles long slash-heavy output and still discovers a later file path", () => {
    const output = `${"/tmp/part".repeat(8000)}\nSaved local/report.md`;
    const start = performance.now();
    const paths = collectChatFilePaths(
      [toolMsg({ name: "write_file", arguments: "{}", output })],
      "A1",
    );
    console.info("slash-heavy tool output benchmark", {
      outputBytes: output.length,
      elapsedMs: performance.now() - start,
    });
    expect(paths).toEqual(["local/report.md"]);
  });

  it("reuses parsed results but detects a replaced message with the same id", () => {
    const original = toolMsg({
      name: "write_file",
      arguments: '{"path":"outbound/first.md"}',
      output: '{"log":"saved"}',
    });
    collectChatFilePaths([original], "A1");
    const parse = vi.spyOn(JSON, "parse");
    try {
      expect(collectChatFilePaths([original], "A1")).toEqual([
        "outbound/first.md",
      ]);
      expect(parse).not.toHaveBeenCalled();
      const updated = {
        ...original,
        toolData: {
          ...original.toolData!,
          arguments: '{"path":"outbound/second.md"}',
        },
      };
      expect(collectChatFilePaths([updated], "A1")).toEqual([
        "outbound/second.md",
      ]);
      expect(parse).toHaveBeenCalled();
    } finally {
      parse.mockRestore();
    }
  });

  it("keeps file list identity and avoids a derived-state rerender on text tokens", () => {
    let renders = 0;
    const tool = toolMsg({
      name: "write_file",
      arguments: '{"path":"outbound/report.md"}',
    });
    const { result, rerender } = renderHook(
      ({ messages }) => {
        renders++;
        return useChatFileDetection("thread", messages, "A1");
      },
      { initialProps: { messages: [tool] } },
    );
    const initialPaths = result.current.filePaths;
    expect(initialPaths).toEqual(["outbound/report.md"]);
    expect(renders).toBe(1);
    rerender({
      messages: [
        tool,
        { id: "text", role: "assistant", content: "new token", timestamp: 1 },
      ],
    });
    expect(renders).toBe(2);
    expect(result.current.filePaths).toBe(initialPaths);
  });
});
