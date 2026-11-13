import { act, renderHook } from "@testing-library/react";
import { expect, it } from "vitest";
import { usePendingRecordingSkill } from "./usePendingRecordingSkill";

it("keeps delayed generation and confirmation in the initiating expert and thread", async () => {
  const first = { agent: "expert", thread: "a" };
  const second = { agent: "expert", thread: "b" };
  const { result, rerender } = renderHook(
    ({ agent, thread }) => usePendingRecordingSkill(agent, thread),
    { initialProps: first },
  );
  const saveFirst = result.current[1];
  let finish!: () => void;
  const delayed = new Promise<void>((resolve) => {
    finish = resolve;
  }).then(() =>
    saveFirst({ name: "first", content: "script A", recordingId: "r1" }),
  );
  rerender(second);
  act(() =>
    result.current[1]({
      name: "second",
      content: "script B",
      recordingId: "r2",
    }),
  );
  await act(async () => {
    finish();
    await delayed;
  });
  expect(result.current[0]?.content).toBe("script B");
  rerender({ agent: "different", thread: "a" });
  expect(result.current[0]).toBeUndefined();
  rerender(first);
  expect(result.current[0]?.content).toBe("script A");
  act(() => result.current[1](null));
  rerender(second);
  expect(result.current[0]?.content).toBe("script B");
});
