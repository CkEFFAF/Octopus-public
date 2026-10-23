import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter, useLocation } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import WorkspaceNav from "./WorkspaceNav";
const { openConversations } = vi.hoisted(() => ({
  openConversations: vi.fn(),
}));
vi.mock("../pages/Chat/hooks/useChatSidebarState", () => ({
  useChatSidebarOpen: () => [false, openConversations],
}));

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
  it("restores the conversation list without leaving the selected conversation", () => {
    render(
      <MemoryRouter initialEntries={["/chat/expert/conversation"]}>
        <WorkspaceNav
          selectedKey="chat"
          collapsed={false}
          isMobile={false}
          onToggle={() => {}}
        />
        <Location />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "octopus.chat" }));
    expect(openConversations).toHaveBeenCalledWith(true);
    expect(screen.getByTestId("location")).toHaveTextContent(
      "/chat/expert/conversation",
    );
  });
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
