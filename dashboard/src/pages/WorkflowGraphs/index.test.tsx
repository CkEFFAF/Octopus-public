import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type {
  GraphDefinition,
  GraphView,
} from "../../api/modules/workflowGraphs";
import WorkflowGraphs from "./index";

const api = vi.hoisted(() =>
  Object.fromEntries(
    [
      "list",
      "get",
      "runs",
      "save",
      "publish",
      "start",
      "run",
      "timeline",
      "version",
      "normalize",
      "cancelJobs",
    ].map((name) => [name, vi.fn()]),
  ),
);
vi.mock("../../api/modules/workflowGraphs", () => ({ workflowGraphsApi: api }));
vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});
vi.mock("../../context/AgentContext", () => ({
  useAgent: () => ({ agents: [{ agent_id: "expert", name: "Expert" }] }),
}));
vi.mock("../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "UTC",
}));
vi.mock("../../layouts/PageShell", () => ({
  default: ({
    actions,
    children,
  }: {
    actions: React.ReactNode;
    children: React.ReactNode;
  }) => (
    <div>
      {actions}
      {children}
    </div>
  ),
}));

const definition = (label: string): GraphDefinition => ({
  name: label,
  agent_id: "expert",
  nodes: [
    {
      id: "start",
      kind: "entry",
      label: label + " start",
      position: { x: 0, y: 0 },
    },
    {
      id: "end",
      kind: "end",
      label: label + " end",
      position: { x: 300, y: 0 },
    },
  ],
  edges: [{ id: "edge", source: "start", target: "end", port: "next" }],
});
const view = (name = "Draft"): GraphView => ({
  graph_id: "A",
  revision: 1,
  published_revision: 1,
  definition: definition(name),
  issues: [],
  archived: false,
});
const run = {
  id: "run",
  graph_id: "A",
  version: 1,
  status: "running",
  steps: 1,
  max_steps: 100,
  deadline: 2000000000,
  error: "",
  created_at: 1700000000,
  node_states: [],
};

beforeEach(() => {
  vi.resetAllMocks();
  Object.defineProperty(window, "matchMedia", {
    writable: true,
    value: vi.fn().mockImplementation((query: string) => ({
      matches: false,
      media: query,
      onchange: null,
      addListener: vi.fn(),
      removeListener: vi.fn(),
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
      dispatchEvent: vi.fn(),
    })),
  });
  api.list.mockResolvedValue({
    items: [
      { graph_id: "A", name: "Graph A", revision: 1, published_revision: 1 },
    ],
    total: 1,
  });
  api.get.mockResolvedValue(view());
  api.runs.mockResolvedValue({ items: [], total: 0 });
  api.save.mockResolvedValue({ ...view(), revision: 2 });
  api.publish.mockResolvedValue({
    ...view(),
    revision: 2,
    published_revision: 2,
  });
  api.start.mockResolvedValue(run);
  api.run.mockResolvedValue(run);
  api.timeline.mockResolvedValue({ items: [], total: 0 });
  api.version.mockResolvedValue(definition("Published"));
});
afterEach(cleanup);
async function open() {
  render(<WorkflowGraphs />);
  fireEvent.click(
    screen.getByRole("button", { name: "workflowGraph.library" }),
  );
  fireEvent.click(await screen.findByRole("button", { name: /Graph A/ }));
  await screen.findByRole("region", { name: "Draft start" });
}
async function start() {
  fireEvent.click(
    screen.getByRole("button", { name: "workflowGraph.settings" }),
  );
  const startButton = await screen.findByRole("button", {
    name: "workflowGraph.start",
  });
  await waitFor(() => expect(startButton).toBeEnabled());
  fireEvent.click(startButton);
  // rc-util assigns every dialog the same title ID in test mode.
  const dialog = (await screen.findByText("workflowGraph.startHelp")).closest(
    '[role="dialog"]',
  ) as HTMLElement;
  fireEvent.click(
    within(dialog).getByRole("button", {
      name: /OK|确.*定/,
    }),
  );
  await screen.findByRole("region", { name: "Published start" });
}

describe("workflow editor orchestration", () => {
  it("keeps workflow actions inside settings and leaves the canvas unobstructed", async () => {
    await open();
    const header = document.querySelector(".wg-header") as HTMLElement;
    expect(
      within(header).getByRole("button", { name: "workflowGraph.settings" }),
    ).toBeVisible();
    expect(
      within(header).queryByRole("button", { name: "workflowGraph.save" }),
    ).not.toBeInTheDocument();
    expect(document.querySelector(".wg-node-panel")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "workflowGraph.runs" }),
    ).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(
      within(header).getByRole("button", { name: "workflowGraph.settings" }),
    );
    for (const action of [
      "save",
      "publish",
      "start",
      "import",
      "export",
      "undo",
      "redo",
    ]) {
      expect(
        await screen.findByRole("button", { name: `workflowGraph.${action}` }),
      ).toBeVisible();
    }
  });

  it("publishes the revision returned by save", async () => {
    await open();
    fireEvent.click(
      screen.getByRole("button", { name: "workflowGraph.settings" }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "workflowGraph.publish" }),
    );
    await waitFor(() => expect(api.publish).toHaveBeenCalledWith("A", 2));
  });

  it("inspects the pinned run definition separately from the editable draft", async () => {
    await open();
    await start();
    expect(api.version).toHaveBeenCalledWith("A", 1);
    expect(
      screen.queryByRole("region", { name: "Draft start" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: "workflowGraph.connectTo Published end",
      }),
    ).not.toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "workflowGraph.editDraft" }),
    );
    expect(
      await screen.findByRole("region", { name: "Draft start" }),
    ).toBeInTheDocument();
  });

  it("installs normalized import defaults before rendering the canvas", async () => {
    await open();
    const raw = {
      name: "Import",
      agent_id: "expert",
      nodes: [{ id: "start", kind: "entry", label: "Import start" }],
      edges: [],
    };
    api.normalize.mockResolvedValue({
      definition: definition("Import"),
      issues: [],
    });
    const file = new File([JSON.stringify(raw)], "workflow.json", {
      type: "application/json",
    });
    Object.defineProperty(file, "text", {
      value: async () => JSON.stringify(raw),
    });
    fireEvent.change(document.querySelector('input[type="file"]')!, {
      target: { files: [file] },
    });
    expect(
      await screen.findByRole("region", { name: "Import start" }),
    ).toBeInTheDocument();
    expect(api.normalize).toHaveBeenCalledWith(raw);
  });

  it("ignores a slow prior selection instead of replacing the current graph", async () => {
    api.list.mockResolvedValue({
      items: [
        { graph_id: "A", name: "Graph A" },
        { graph_id: "B", name: "Graph B" },
      ],
      total: 2,
    });
    let finish!: (value: GraphView) => void;
    api.get.mockImplementation((id: string) =>
      id === "A"
        ? new Promise((resolve) => {
            finish = resolve;
          })
        : Promise.resolve({ ...view("Second"), graph_id: "B" }),
    );
    render(<WorkflowGraphs />);
    fireEvent.click(
      screen.getByRole("button", { name: "workflowGraph.library" }),
    );
    fireEvent.click(await screen.findByRole("button", { name: /Graph A/ }));
    fireEvent.click(screen.getByRole("button", { name: /Graph B/ }));
    await screen.findByRole("region", { name: "Second start" });
    await act(async () => finish(view("Stale")));
    expect(
      screen.getByRole("region", { name: "Second start" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Stale start" }),
    ).not.toBeInTheDocument();
  });
});
