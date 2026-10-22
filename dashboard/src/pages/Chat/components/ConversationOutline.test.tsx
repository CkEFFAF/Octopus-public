import { describe, expect, it } from "vitest";
import { exportOutline } from "./ConversationOutline";

const groups = [
  {
    key: "completed",
    label: "Reported work",
    items: [
      { text: "Reported done", source_refs: [{ kind: "message", id: "1" }] },
    ],
  },
  {
    key: "nextActions",
    label: "Next",
    items: [
      {
        text: 'Verify <script> and "sources"\nnext',
        source_refs: [{ kind: "message", id: "2" }],
      },
    ],
  },
];
describe("conversation outline exports", () => {
  it("preserves source refs and strips structural newlines", () => {
    const value = exportOutline("Topic", groups, "markdown");
    expect(value).toContain("message:1");
    expect(value).toContain("message:2");
    expect(value).not.toContain('"sources"\nnext');
  });
  it("escapes diagram labels without executing source content", () => {
    const value = exportOutline("Topic <img>", groups, "mermaid");
    expect(value).toContain("&lt;img&gt;");
    expect(value).toContain("&quot;sources&quot;");
    expect(value).not.toContain("<script>");
  });
  it("does not turn completed reports into pending todos", () => {
    const value = exportOutline("Topic", groups, "todo");
    expect(value).not.toContain("Reported done");
    expect(value).toContain("- [ ] Verify");
  });
});
