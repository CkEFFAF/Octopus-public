import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import WorkspaceNav from "./WorkspaceNav";

vi.mock("../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({
    id: 1,
    username: "admin",
    role: "admin",
    permissions: ["*"],
  }),
}));
vi.mock("../hooks/useServerCapabilities", () => ({
  useServerCapabilities: () => ({ mobileEnabled: false }),
}));
vi.mock("../components/AvatarDropdown", () => ({ default: () => null }));
function Location() {
  return <output data-testid="location">{useLocation().pathname}</output>;
}
describe("conversation settings navigation", () => {
  it("exposes conversation organization beside Models and retains the settings context", () => {
    const { rerender } = render(
      <MemoryRouter initialEntries={["/admin/models"]}>
        <WorkspaceNav
          selectedKey="models"
          collapsed={false}
          isMobile={false}
          onToggle={() => {}}
        />
        <Location />
      </MemoryRouter>,
    );
    const link = screen.getByRole("button", {
      name: "conversationMetadata.settingsTitle",
    });
    expect(link).toBeVisible();
    fireEvent.click(link);
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/settings/conversation-metadata",
    );
    rerender(
      <MemoryRouter>
        <WorkspaceNav
          selectedKey="conversation-metadata"
          collapsed={false}
          isMobile={false}
          onToggle={() => {}}
        />
        <Location />
      </MemoryRouter>,
    );
    expect(
      screen.getByRole("button", {
        name: "conversationMetadata.settingsTitle",
      }),
    ).toHaveClass("active");
    expect(
      screen.getByRole("button", { name: "octopus.settings" }),
    ).toHaveAttribute("aria-current", "page");
  });
});
