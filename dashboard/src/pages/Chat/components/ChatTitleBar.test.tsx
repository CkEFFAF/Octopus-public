import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import ChatTitleBar from "./ChatTitleBar";
import type { Session } from "../hooks/useSessions";

const session: Session = {
  id: "s1",
  name: "Weekly recap",
  threadId: "t1",
  updatedAt: null,
  channelType: "web",
};

const noop = vi.fn();

describe("ChatTitleBar", () => {
  it("places expert activity beside the title without absorbing its controls", () => {
    render(
      <ChatTitleBar
        session={session}
        title="Weekly recap"
        onRename={noop}
        onPin={noop}
        onFork={noop}
        onDelete={noop}
        activity={<span data-testid="expert-activity">Expert · Idle</span>}
      />,
    );
    const heading = screen.getByRole("heading", { name: "Weekly recap" });
    const activity = screen.getByTestId("expert-activity");
    expect(heading.parentElement).not.toContainElement(activity);
    expect(heading.parentElement?.parentElement).toBe(activity.parentElement);
    expect(
      screen.getByRole("button", { name: "common.edit" }),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "更多" })).toBeInTheDocument();
  });

  it("keeps the more menu beside the title edit control", () => {
    render(
      <ChatTitleBar
        session={session}
        title="Weekly recap"
        onRename={noop}
        onPin={noop}
        onFork={noop}
        onDelete={noop}
      />,
    );

    const heading = screen.getByRole("heading", { name: "Weekly recap" });
    const edit = screen.getByRole("button", { name: "common.edit" });
    const more = screen.getByRole("button", { name: "更多" });

    expect(heading.parentElement).toContainElement(edit);
    expect(heading.parentElement).toContainElement(more);
  });

  it("marks the title bar as a Wails drag region", () => {
    const { container } = render(
      <ChatTitleBar
        session={session}
        title="Weekly recap"
        onRename={noop}
        onPin={noop}
        onFork={noop}
        onDelete={noop}
      />,
    );

    expect(container.querySelector(".octop-desktop-drag")).not.toBeNull();
  });

  it("shows a team badge next to the title for group chats", () => {
    render(
      <ChatTitleBar
        session={session}
        title="Weekly recap"
        onRename={noop}
        onPin={noop}
        onFork={noop}
        onDelete={noop}
        isTeam
      />,
    );

    expect(screen.getByLabelText("chat.teamBadge")).toBeInTheDocument();
  });
});
