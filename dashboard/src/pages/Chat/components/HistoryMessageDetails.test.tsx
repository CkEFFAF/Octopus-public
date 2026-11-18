import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { octopThreadsApi } from "../../../api/modules/octopThreads";
import { HistoryMessageDetails } from "./HistoryMessageDetails";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

it("loads only the requested stored message on demand and allows retry", async () => {
  const content = [
    { type: "text", text: "Complete answer" },
    { type: "thinking", thinking: "Complete reasoning" },
  ];
  const load = vi
    .spyOn(octopThreadsApi, "history")
    .mockResolvedValueOnce({
      thread_id: "thread",
      messages: [{ role: "assistant", content }],
    })
    .mockResolvedValueOnce({
      thread_id: "thread",
      detail_cursor: "saved-position",
      messages: [{ role: "assistant", content }],
    });
  render(
    <HistoryMessageDetails
      detail={{
        agentId: "agent",
        threadId: "thread",
        cursor: "saved-position",
      }}
    />,
  );

  expect(load).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "chat.historyFullMessage" }),
  );
  await screen.findByText("chat.historyFullMessageFailed");
  expect(screen.queryByDisplayValue("Complete answer")).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
  await screen.findByDisplayValue("Complete answer");
  expect(screen.getByDisplayValue("Complete reasoning")).toBeTruthy();
  expect(load).toHaveBeenCalledTimes(2);
  expect(load).toHaveBeenLastCalledWith(
    "agent",
    "thread",
    expect.objectContaining({ limit: 1, cursor: "saved-position" }),
  );
});
