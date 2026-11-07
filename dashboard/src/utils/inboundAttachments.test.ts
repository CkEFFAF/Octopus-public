import { describe, expect, it } from "vitest";
import { parseHarnessChunk } from "./parseHarnessChunk";
import { inboundAttachments } from "./inboundAttachments";
describe("verified inserted attachments", () => {
  it("preserves the display text, image and immutable resource version", () => {
    const canonical = [
      {
        filename: "补充.png",
        media_type: "image/png",
        kind: "image",
        workspace_path: "inbound/补充.png",
        resource_id: "res_verified",
        version: "a".repeat(64),
      },
    ];
    const chunk = parseHarnessChunk(
      "data: " +
        JSON.stringify({
          type: "user",
          source: "dashboard_insert",
          command_id: "media",
          content: "",
          inbound_attachments: canonical,
        }),
    );
    expect(chunk).toMatchObject({
      type: "user",
      content: "",
      snapshot: {
        attachments: [
          {
            filename: "补充.png",
            kind: "image",
            workspacePath: "inbound/补充.png",
            resourceId: "res_verified",
            version: "a".repeat(64),
          },
        ],
      },
    });
    expect(JSON.stringify(chunk)).not.toContain("base64");
  });
  it("ignores malformed media metadata and retains a queued snapshot", () => {
    expect(inboundAttachments([null, "bad", { filename: "no path" }])).toEqual(
      [],
    );
    expect(
      parseHarnessChunk(
        "data: " +
          JSON.stringify({
            type: "user",
            content: "next",
            snapshot: {
              attachments: [
                { url: "/api/file", kind: "file", filename: "qa.txt" },
              ],
            },
          }),
      ),
    ).toMatchObject({ snapshot: { attachments: [{ filename: "qa.txt" }] } });
  });
});
