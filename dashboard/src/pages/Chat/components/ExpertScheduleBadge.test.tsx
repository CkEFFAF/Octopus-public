import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import ExpertScheduleBadge from "./ExpertScheduleBadge";

vi.mock("../hooks/useSidebarActivity", () => ({
  useSidebarActivity: () => ({
    expert: { schedules: [], schedule_counts: { schedules: 3, reminders: 8 } },
  }),
}));

vi.mock("../../../components/ScheduleBrowser", () => ({
  default: () => <div>schedule-browser</div>,
}));

function Location() {
  const value = useLocation();
  return <output>{value.pathname + value.search}</output>;
}
describe("expert schedule shortcuts", () => {
  it("opens the expert's task panel without selecting the expert row", () => {
    const select = vi.fn();
    render(
      <MemoryRouter>
        <div onClick={select}>
          <ExpertScheduleBadge agentId="expert" />
          <Location />
        </div>
      </MemoryRouter>,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "workspace0034.expertTaskPanel" }),
    );
    expect(select).not.toHaveBeenCalled();
    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(
      screen.getByRole("tab", { name: "workspace0034.backgroundSummary" }),
    ).toHaveAttribute("aria-selected", "true");
    fireEvent.click(
      screen.getByRole("tab", { name: "workspace0034.schedules" }),
    );
    fireEvent.click(screen.getByText("schedule-browser"));
    expect(select).not.toHaveBeenCalled();
    expect(screen.getByRole("status")).toHaveTextContent("/");
  });
  it("keeps the task button available for an expert without schedules", () => {
    render(
      <MemoryRouter>
        <ExpertScheduleBadge agentId="empty" />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("button", { name: "workspace0034.expertTaskPanel" }),
    ).toBeInTheDocument();
  });
  it("does not expose task management for a shared expert", () => {
    render(
      <MemoryRouter>
        <ExpertScheduleBadge agentId="empty" owned={false} />
      </MemoryRouter>,
    );
    expect(screen.queryByRole("button")).toBeNull();
  });
});
