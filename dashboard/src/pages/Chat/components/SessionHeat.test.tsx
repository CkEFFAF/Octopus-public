import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import SessionHeat from "./SessionHeat";
import { sortSessions, toSession } from "../hooks/useSessions";
import type { ThreadHeat } from "../../../api/modules/octopThreads";
const heat: ThreadHeat = {
  score: 78,
  level: "running",
  interactions_24h: 5,
  interactions_7d: 12,
  work_7d: 3,
  background_count: 1,
  attention_count: 0,
  last_user_at: 1,
  next_overview_at: 0,
};
it("uses a text label in addition to the task color", () => {
  render(<SessionHeat heat={heat} />);
  expect(screen.getByText("sessionHeat.level.running")).toBeVisible();
  expect(screen.getByLabelText("sessionHeat.score")).toHaveAttribute(
    "tabindex",
    "0",
  );
});
it("preserves pin priority, then ranks older hot sessions above recent quiet ones", () => {
  const base = { title: "Chat", last_active: 1, channel_type: "dashboard" };
  const hot = toSession({ ...base, thread_id: "old-hot", heat });
  const recent = toSession({ ...base, thread_id: "recent", last_active: 100 });
  const pin = toSession({ ...base, thread_id: "pin", pinned: true });
  expect(sortSessions([recent, hot, pin]).map((row) => row.id)).toEqual([
    "pin",
    "old-hot",
    "recent",
  ]);
});
