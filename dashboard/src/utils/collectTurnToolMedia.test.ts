import { describe, expect, it, vi } from "vitest";
import type { ChatMessage } from "../pages/Chat/hooks/useChat";
import { collectMessageToolMedia } from "./collectTurnToolMedia";

describe("message tool media caching", () => {
  it("shares settled parsing while refreshing output, attachments, and owner changes", () => {
    const message: ChatMessage = {
      id: "tool",
      role: "assistant",
      content: "",
      timestamp: 1,
      toolData: {
        name: "read_file",
        arguments: "{}",
        output: JSON.stringify([
          { type: "file", path: "outbound/first.pdf", filename: "first.pdf" },
        ]),
      },
    };
    const first = collectMessageToolMedia(message, "A1");
    expect(first.files[0]?.url).toContain("/agents/A1/");
    const parse = vi.spyOn(JSON, "parse");
    try {
      expect(collectMessageToolMedia(message, "A1")).toBe(first);
      expect(parse).not.toHaveBeenCalled();
      const otherOwner = collectMessageToolMedia(message, "A2");
      expect(otherOwner.files[0]?.url).toContain("/agents/A2/");
      const updatedOutput = {
        ...message,
        toolData: {
          ...message.toolData!,
          output: JSON.stringify([
            {
              type: "file",
              path: "outbound/second.pdf",
              filename: "second.pdf",
            },
          ]),
        },
      };
      expect(
        collectMessageToolMedia(updatedOutput, "A1").files[0]?.filename,
      ).toBe("second.pdf");
      const updatedAttachments: ChatMessage = {
        ...message,
        attachments: [
          {
            url: "outbound/attached.pdf",
            kind: "file",
            filename: "attached.pdf",
          },
        ],
      };
      expect(
        collectMessageToolMedia(updatedAttachments, "A1").files.map(
          (f) => f.filename,
        ),
      ).toContain("attached.pdf");
    } finally {
      parse.mockRestore();
    }
  });
});
