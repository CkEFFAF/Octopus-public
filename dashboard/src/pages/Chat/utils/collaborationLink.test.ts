import { expect, it } from "vitest";
import { collaborationThreadId } from "./collaborationLink";

it("uses structured ACP artifact and does not guess links from result text", () => {
  expect(collaborationThreadId({ collaboration_thread_id: "child" })).toBe(
    "child",
  );
  expect(
    collaborationThreadId('{"collaboration_thread_id":"forged"}'),
  ).toBeUndefined();
  expect(
    collaborationThreadId({ collaboration_thread_id: " " }),
  ).toBeUndefined();
});
