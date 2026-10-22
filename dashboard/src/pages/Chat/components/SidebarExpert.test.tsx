import {
  fireEvent,
  render,
  screen,
  within,
  cleanup,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { OctopAgent } from "../../../context/AgentContext";
import SessionList from "./SessionList";
import { sidebarExpertPhase } from "./SidebarExpert";

let userId = 1;
vi.mock("../../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ id: userId }),
}));
vi.mock("react-i18next", () => ({
  useTranslation: () => ({ t: (key: string) => key }),
}));

const expert = (id: number, extra: Partial<OctopAgent> = {}): OctopAgent =>
  ({
    id,
    agent_id: `expert-${id}`,
    name: `Expert ${id}`,
    state: "running",
    icon_url: "/expert-animations/fox.webp",
    color: "#f97316",
    ...extra,
  }) as OctopAgent;

function mount(agents = [expert(1), expert(2)]) {
  const onAgentSelect = vi.fn();
  const view = render(
    <MemoryRouter>
      <SessionList
        agents={agents}
        sessions={[]}
        activeId={null}
        activeAgentId="expert-1"
        hasMore={false}
        loadingMore={false}
        onLoadMore={vi.fn()}
        onFetchAllSessions={vi.fn()}
        onSelect={vi.fn()}
        onAgentSelect={onAgentSelect}
        onNewChat={vi.fn()}
        onDelete={vi.fn()}
        onRename={vi.fn()}
        onPin={vi.fn()}
        onFork={vi.fn()}
      />
    </MemoryRouter>,
  );
  return { ...view, onAgentSelect };
}

beforeEach(() => {
  localStorage.clear();
  userId = 1;
});
afterEach(cleanup);

describe("sidebar expert shortcuts", () => {
  it.each(["{Enter}", " "])(
    "pins with %s without selecting the expert row",
    async (key) => {
      const view = mount();
      const row = screen
        .getByText("Expert 2")
        .closest('[role="button"]') as HTMLElement;
      const pin = within(row).getByLabelText("chat.pinExpert");
      pin.focus();
      await userEvent.keyboard(key);
      expect(view.onAgentSelect).not.toHaveBeenCalled();
      expect(
        screen.getByRole("region", { name: "chat.pinnedExperts" }),
      ).toBeVisible();
    },
  );
  it("pins, restores, opens and unpins an expert without selecting the row when pinning", () => {
    let view = mount();
    fireEvent.click(
      within(
        screen.getByText("Expert 2").closest('[role="button"]') as HTMLElement,
      ).getByLabelText("chat.pinExpert"),
    );
    expect(view.onAgentSelect).not.toHaveBeenCalled();
    const pinned = screen.getByRole("region", { name: "chat.pinnedExperts" });
    fireEvent.click(within(pinned).getByRole("button", { name: /Expert 2/ }));
    expect(view.onAgentSelect).toHaveBeenCalledWith("expert-2");
    view.unmount();
    view = mount();
    const restored = screen.getByRole("region", { name: "chat.pinnedExperts" });
    expect(within(restored).getByText("Expert 2")).toBeVisible();
    fireEvent.click(within(restored).getByLabelText("chat.unpinExpert"));
    expect(
      screen.queryByRole("region", { name: "chat.pinnedExperts" }),
    ).toBeNull();
  });

  it("keeps pins private to the signed-in account and filters shortcuts by search", () => {
    const view = mount();
    fireEvent.click(
      within(
        screen.getByText("Expert 2").closest('[role="button"]') as HTMLElement,
      ).getByLabelText("chat.pinExpert"),
    );
    fireEvent.change(screen.getByRole("searchbox"), {
      target: { value: "no match" },
    });
    expect(
      screen.queryByRole("region", { name: "chat.pinnedExperts" }),
    ).toBeNull();
    view.unmount();
    userId = 2;
    mount();
    expect(
      screen.queryByRole("region", { name: "chat.pinnedExperts" }),
    ).toBeNull();
  });

  it("shows a working label for a background expert and idle for a ready expert", () => {
    mount([expert(1), expert(2, { is_working: true })]);
    expect(screen.getByText("expertAnimation.phases.running")).toBeVisible();
    expect(screen.getByText("expertAnimation.phases.idle")).toBeVisible();
  });
});

describe("sidebar expert phases", () => {
  it("preserves real waits and lifecycle errors while distinguishing server activity from readiness", () => {
    expect(sidebarExpertPhase(expert(1))).toBe("idle");
    expect(sidebarExpertPhase(expert(1, { is_working: true }))).toBe("running");
    expect(
      sidebarExpertPhase(expert(1, { is_working: true }), "waiting_permission"),
    ).toBe("waiting_permission");
    expect(
      sidebarExpertPhase(expert(1, { bridge_disconnected: true }), "thinking"),
    ).toBe("offline");
    expect(sidebarExpertPhase(expert(1, { state: "failed" }), "thinking")).toBe(
      "error",
    );
  });
});
