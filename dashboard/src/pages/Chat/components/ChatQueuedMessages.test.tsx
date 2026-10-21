import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ChatQueuedMessages from "./ChatQueuedMessages";

const items = [
  { id: "first", text: "check memory", createdAt: 1, status: "queued" },
  { id: "second", text: "check disks", createdAt: 2, status: "queued" },
];

describe("queued message controls", () => {
  it("lets an unconfirmed receipt be dismissed without inserting or reclaiming it", async () => {
    const onSteer = vi.fn();
    const onReclaim = vi.fn();
    const onDismiss = vi.fn().mockResolvedValue(true);
    render(
      <ChatQueuedMessages
        items={[{ ...items[0], status: "unknown" }]}
        onReclaim={onReclaim}
        onSteer={onSteer}
        onDismiss={onDismiss}
        canSteer
      />,
    );
    expect(
      screen.queryByRole("button", { name: "chat.steer.immediateAction" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "chat.queue.dismiss" }));
    await act(async () => {});
    expect(onDismiss).toHaveBeenCalledExactlyOnceWith("first");
    expect(onSteer).not.toHaveBeenCalled();
    expect(onReclaim).not.toHaveBeenCalled();
  });
  it("inserts only the selected queued message and blocks duplicate clicks while pending", async () => {
    let resolve!: (value: boolean) => void;
    const onSteer = vi.fn(
      () =>
        new Promise<boolean>((done) => {
          resolve = done;
        }),
    );
    const onReclaim = vi.fn();
    render(
      <ChatQueuedMessages
        items={items}
        onReclaim={onReclaim}
        onSteer={onSteer}
        canSteer
      />,
    );
    const insert = screen.getAllByRole("button", {
      name: "chat.steer.action",
    })[1];
    fireEvent.click(insert);
    fireEvent.click(insert);
    expect(onSteer).toHaveBeenCalledExactlyOnceWith("second", false);
    expect(onReclaim).not.toHaveBeenCalled();
    expect(
      screen.getAllByRole("button", { name: "chat.queue.withdraw" })[0],
    ).toBeDisabled();
    await act(async () => resolve(false));
    expect(screen.getAllByRole("listitem")).toHaveLength(2);
    expect(insert).toBeEnabled();
  });

  it("offers immediate interruption for the selected queued message", async () => {
    const onSteer = vi.fn().mockResolvedValue(true);
    render(
      <ChatQueuedMessages
        items={items}
        onReclaim={vi.fn()}
        onSteer={onSteer}
        canSteer
      />,
    );
    fireEvent.click(
      screen.getAllByRole("button", { name: "chat.steer.immediateAction" })[1],
    );
    await act(async () => {});
    expect(onSteer).toHaveBeenCalledExactlyOnceWith("second", true);
    expect(
      screen.getAllByRole("button", { name: "chat.steer.action" }),
    ).toHaveLength(2);
  });

  it("withdraws the selected message for editing without inserting it", () => {
    const onReclaim = vi.fn();
    const onSteer = vi.fn();
    render(
      <ChatQueuedMessages
        items={items}
        onReclaim={onReclaim}
        onSteer={onSteer}
        canSteer
      />,
    );
    fireEvent.click(
      screen.getAllByRole("button", { name: "chat.queue.withdraw" })[0],
    );
    expect(onReclaim).toHaveBeenCalledExactlyOnceWith("first");
    expect(onSteer).not.toHaveBeenCalled();
  });

  it("keeps attachments and commands queued and prevents modifying accepted work", () => {
    render(
      <ChatQueuedMessages
        items={[
          { ...items[0], text: "/clear" },
          { ...items[1], attachments: [{ name: "file.pdf" } as never] },
          {
            id: "accepted",
            text: "already inserting",
            createdAt: 3,
            status: "accepted",
          },
        ]}
        onReclaim={vi.fn()}
        onSteer={vi.fn()}
        canSteer
      />,
    );
    for (const name of ["chat.steer.action", "chat.steer.immediateAction"]) {
      for (const button of screen.getAllByRole("button", { name })) {
        expect(button).toBeDisabled();
      }
    }
    expect(
      screen.getAllByRole("button", { name: "chat.queue.withdraw" })[2],
    ).toBeDisabled();
  });

  it("keeps insertion disabled after the active run ends", () => {
    render(
      <ChatQueuedMessages
        items={items}
        onReclaim={vi.fn()}
        onSteer={vi.fn()}
      />,
    );
    expect(
      screen.getAllByRole("button", { name: "chat.steer.action" })[0],
    ).toBeDisabled();
    expect(
      screen.getAllByRole("button", { name: "chat.queue.withdraw" })[0],
    ).toBeEnabled();
  });
});
