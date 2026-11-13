import { expect, it } from "vitest";
import type { ConversationEvent } from "../../../api/modules/conversationMetadata";
import { groupOverviewEvents, overviewTitle } from "./overviewEvents";

const event = (
  id: number,
  kind = "execution",
  text = "",
): ConversationEvent => ({
  event_id: String(id),
  kind,
  text,
  occurred_at: 100 + id,
  recorded_at: 100 + id,
  author_kind: "runtime",
  source_refs: [],
  details: {},
});
it("folds repeated execution summaries while preserving each evidence reference", () => {
  const events = [event(1), event(2), event(3, "decision", "Use v2"), event(4)];
  const groups = groupOverviewEvents(events);
  expect(groups.map((group) => group.length)).toEqual([2, 1, 1]);
  expect(groups.flat()).toEqual(events);
  expect(groupOverviewEvents([event(1), event(70)])).toHaveLength(2);
});
it("cleans markdown title syntax without changing the source", () => {
  expect(overviewTitle("**双偏置**：几何 bias ⊕ `类别 bias`")).toBe(
    "双偏置：几何 bias ⊕ 类别 bias",
  );
});
