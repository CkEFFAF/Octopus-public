import { render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  connectorsApi,
  type ConnectorInstance,
} from "../../api/modules/connectors";
import { CONNECTORS_CHANGED_EVENT } from "../../utils/connectorEvents";
import { SharedMcpMarket } from ".";

vi.mock("../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ id: 2, role: "user" }),
}));

function connector(overrides: Partial<ConnectorInstance>): ConnectorInstance {
  return {
    instance_id: "shared-http",
    kind: "custom-mcp",
    transport: "streamable_http",
    display_name: "Shared HTTP",
    status: "active",
    mcp_server_name: "custom__owner__http",
    has_credentials: true,
    shared: true,
    owner_user_id: 1,
    owner_display_name: "Publisher",
    can_manage: false,
    created_at: 0,
    updated_at: 0,
    ...overrides,
  };
}

afterEach(() => vi.restoreAllMocks());

describe("SharedMcpMarket", () => {
  it("shows active shared servers and respects the stdio execution boundary", async () => {
    vi.spyOn(connectorsApi, "listInstances").mockResolvedValue([
      connector({}),
      connector({
        instance_id: "stdio",
        display_name: "Shared stdio",
        transport: "stdio",
      }),
      connector({
        instance_id: "private",
        display_name: "Private",
        shared: false,
      }),
      connector({
        instance_id: "disabled",
        display_name: "Disabled",
        status: "disabled",
      }),
    ]);
    render(
      <MemoryRouter>
        <SharedMcpMarket />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Shared HTTP")).toBeInTheDocument();
    expect(screen.getByText("Shared stdio")).toBeInTheDocument();
    expect(screen.queryByText("Private")).not.toBeInTheDocument();
    expect(screen.queryByText("Disabled")).not.toBeInTheDocument();
    expect(
      screen.getByText("connectors.sharedMcpMarket.stdioRestricted"),
    ).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/experts");
  });

  it("removes an entry after the owner revokes sharing", async () => {
    const list = vi.spyOn(connectorsApi, "listInstances");
    list.mockResolvedValueOnce([connector({})]).mockResolvedValue([]);
    render(
      <MemoryRouter>
        <SharedMcpMarket />
      </MemoryRouter>,
    );
    expect(await screen.findByText("Shared HTTP")).toBeInTheDocument();
    window.dispatchEvent(new CustomEvent(CONNECTORS_CHANGED_EVENT));
    await waitFor(() =>
      expect(screen.queryByText("Shared HTTP")).not.toBeInTheDocument(),
    );
  });
});
