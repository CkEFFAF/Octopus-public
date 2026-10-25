import { App } from "antd";
import { render, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { OctopAgent } from "../../../context/AgentContext";
import EditAgentDrawer from "./EditAgentDrawer";

vi.mock("../../Agent/Workspace/components/WorkspaceDrawer", () => ({
  default: () => null,
}));
vi.mock("../../../components/PdfDocumentPreview", () => ({
  default: () => null,
}));

vi.mock("../../../api/request", async (original) => ({
  ...(await original<typeof import("../../../api/request")>()),
  request: vi.fn().mockResolvedValue({
    id: "test",
    name: "Fresh detail",
    is_shared: true,
    color: null,
    config: {},
  }),
}));
vi.mock("../../../context/AgentContext", () => ({
  useAgent: () => ({ refresh: vi.fn() }),
}));
vi.mock("../../../hooks/useAgentFormResources", () => ({
  useAgentFormResources: () => ({
    models: [],
    backends: [],
    modelsLoading: false,
    backendsLoading: false,
  }),
}));
vi.mock("../../../api/modules/devices", () => ({
  devicesApi: { list: vi.fn().mockResolvedValue({ devices: [] }) },
}));

it("hydrates sharing from the fetched detail instead of an older list row", async () => {
  const staleRow: OctopAgent = {
    id: 1,
    agent_id: "test",
    name: "Stale list",
    is_shared: false,
    description: null,
    persona_mbti: null,
    default_model: null,
    system_prompt: null,
    template_name: null,
    state: "stopped",
    last_error: null,
    icon: null,
    icon_name: null,
    icon_url: null,
    color: null,
    config: {},
  };
  render(
    <App>
      <EditAgentDrawer
        open
        agent={staleRow}
        onClose={vi.fn()}
        onSaved={vi.fn()}
      />
    </App>,
  );
  await waitFor(() =>
    expect(screen.getByLabelText("experts.agentName")).toHaveValue(
      "Fresh detail",
    ),
  );
  expect(
    screen.getByRole("switch", { name: "experts.share.toggle" }),
  ).toBeChecked();
});
