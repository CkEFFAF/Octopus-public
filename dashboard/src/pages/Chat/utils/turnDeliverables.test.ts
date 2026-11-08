import { expect, it } from "vitest";
import type {
  CollaborationPage,
  CollaborationResource,
  CollaborationInvocation,
} from "../../../api/modules/collaboration";
import type { ChatMessage } from "../hooks/useChat";
import { groupConsecutiveAssistantMessages } from "./messageGrouping";
import { turnDeliverables } from "./turnDeliverables";
const message = (
  id: string,
  role: ChatMessage["role"],
  timestamp: number,
  extra: Partial<ChatMessage> = {},
): ChatMessage => ({ id, role, timestamp, content: "", ...extra });
const resource = (id: string, time: number): CollaborationResource =>
  ({
    resource_id: id,
    version: "v1",
    source_agent_id: "host",
    source_thread_id: "thread",
    source_kind: "device",
    name: `${id}.png`,
    media_type: "image/png",
    size: 12,
    publication_state: "published",
    created_at: time,
  }) as CollaborationResource;
const page = (artifacts: CollaborationResource[]): CollaborationPage => ({
  artifacts,
  invocations: [],
  events: [],
  has_more: false,
  next_cursor: 0,
});
it("keeps a legacy delivered image under its original answer after another user message", () => {
  const groups = groupConsecutiveAssistantMessages([
    message("u1", "user", 1000),
    message("a1", "assistant", 3000),
    message("u2", "user", 9000),
    message("a2", "assistant", 10000),
  ]);
  const result = turnDeliverables(
    groups,
    page([resource("image", 2)]),
    "host",
    "thread",
  );
  expect(result.get("a1")?.map((item) => item.resource_id)).toEqual(["image"]);
  expect(result.has("a2")).toBe(false);
});
it("uses exact publication references for repeat delivery instead of relying on resource creation time", () => {
  const groups = groupConsecutiveAssistantMessages([
    message("u1", "user", 1000),
    message("a1", "assistant", 3000),
    message("u2", "user", 9000),
    message("a2", "assistant", 10000, {
      toolData: {
        name: "publish_artifact",
        output: '{"status":"published","resource_id":"image"}',
      },
    }),
  ]);
  const result = turnDeliverables(
    groups,
    page([resource("image", 2)]),
    "host",
    "thread",
  );
  expect(result.get("a2")?.[0].resource_id).toBe("image");
});
it("does not assign unloaded history, other experts, uploads or withdrawn resources to the latest reply", () => {
  const groups = groupConsecutiveAssistantMessages([
    message("u2", "user", 9000),
    message("a2", "assistant", 10000),
  ]);
  const result = turnDeliverables(
    groups,
    page([
      resource("old", 2),
      { ...resource("peer", 9.5), source_agent_id: "peer" },
      { ...resource("upload", 9.5), source_kind: "upload" },
      { ...resource("failed", 9.5), publication_state: "unavailable" },
    ]),
    "host",
    "thread",
  );
  expect(result.size).toBe(0);
});
it("keeps asynchronous child results with the requesting answer across later user turns", () => {
  const groups = groupConsecutiveAssistantMessages([
    message("u1", "user", 1000),
    message("a1", "assistant", 3000),
    message("u2", "user", 9000),
    message("a2", "assistant", 10000),
  ]);
  const payload = page([
    {
      ...resource("child-result", 12),
      source_agent_id: "child",
      source_thread_id: "child-thread",
    },
  ]);
  payload.invocations = [
    {
      source_agent_id: "host",
      created_at: 2,
      task_result: {
        resources: [{ resource_id: "child-result", version: "v1" }],
      },
    } as CollaborationInvocation,
  ];
  expect(
    turnDeliverables(groups, payload, "host", "thread").get("a1")?.[0]
      .resource_id,
  ).toBe("child-result");
});
