import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import ConversationReferences from "./ConversationReferences";

it("collapses many references, deduplicates them, and reads only the selected original", async () => {
  const refs = Array.from({ length: 43 }, (_, index) => ({
    kind: "message",
    id: String(index),
  }));
  const onRead = vi.fn();
  render(<ConversationReferences refs={[...refs, refs[0]]} onRead={onRead} />);
  expect(screen.getAllByRole("button")).toHaveLength(1);
  expect(onRead).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "conversationMetadata.sourcesCount" }),
  );
  const source = await screen.findByRole("button", {
    name: "conversationMetadata.source 1",
  });
  expect(
    screen.queryByRole("button", { name: "conversationMetadata.source 11" }),
  ).not.toBeInTheDocument();
  fireEvent.click(source);
  expect(onRead).toHaveBeenCalledExactlyOnceWith(refs[0]);
});
