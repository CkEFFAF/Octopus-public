import { useState } from "react";
import { MemoryRouter, useLocation } from "react-router-dom";
import WelcomeScreen from "../pages/Chat/components/WelcomeScreen";
import ProjectRoomBar from "../pages/Chat/components/ProjectRoomBar";
import { ExpertMessageAvatar } from "../pages/Chat/components/MessageSender";
import { ChatAgentProfileProvider } from "../pages/Chat/ChatAgentProfileContext";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { App } from "antd";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { OctopAgent } from "../context/AgentContext";

vi.mock("react-i18next", () => {
  const t = (key: string) => key;
  return { useTranslation: () => ({ t }) };
});

const state = vi.hoisted(() => ({
  agents: [] as OctopAgent[],
  patch: vi.fn(),
  refresh: vi.fn(),
  setActiveAgent: vi.fn(),
  failSave: false,
  failLoad: false,
}));
vi.mock("../context/AgentContext", () => ({
  useAgent: () => ({
    agents: state.agents,
    refresh: state.refresh,
    setActiveAgent: state.setActiveAgent,
  }),
}));
vi.mock("../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ id: 7, role: "user" }),
}));
vi.mock("../hooks/useAgentFormResources", () => ({
  useAgentFormResources: () => ({
    models: [
      { provider_name: "provider", model: "old" },
      { provider_name: "provider", model: "new" },
    ],
    modelsLoading: false,
    backends: [],
    backendsLoading: false,
  }),
}));
vi.mock("../api/request", () => ({
  request: vi.fn(
    async (path: string, options?: { method?: string; body?: string }) => {
      if (path.endsWith("/skills") || path.endsWith("/subagents")) return [];
      const row = state.agents.find(
        (agent) => path === `/agents/${agent.agent_id}`,
      );
      if (!row || state.failLoad) throw new Error("Load failed");
      if (options?.method === "PATCH") {
        const body = JSON.parse(options.body ?? "{}");
        state.patch(row.agent_id, body);
        if (state.failSave) throw new Error("Save failed");
        Object.assign(row, body);
      }
      return structuredClone(row);
    },
  ),
}));
vi.mock("../api/modules/teams", () => ({
  teamsApi: {
    get: vi.fn(async () => ({
      name: "Research crew",
      description: "Team",
      members: state.agents.map((agent) => ({
        ...agent,
        model_ref: agent.default_model,
        default_target: agent.config.device_binding,
      })),
    })),
  },
}));
vi.mock("../api/modules/devices", () => ({
  devicesApi: {
    list: vi.fn(async () => ({
      devices: [
        {
          device_id: "laptop",
          name: "Laptop",
          online: true,
          revoked_at: null,
          trust_mode: "owner",
          roots: [],
          runtime: {},
        },
      ],
    })),
  },
}));
vi.mock("../api/modules/subagents", () => ({
  listAgentSubagents: vi.fn(async () => []),
}));
vi.mock("../pages/Experts/components/expertFileGroups", () => ({
  fetchConfigMdFiles: vi.fn(async () => []),
}));
vi.mock("../pages/Experts/components/WelcomeConfig", () => ({
  default: () => null,
}));
vi.mock("../pages/Experts/components/SkillCatalogDrawer", () => ({
  default: () => null,
}));
vi.mock("../pages/Experts/components/SubagentCatalogDrawer", () => ({
  default: () => null,
}));
vi.mock("../pages/Experts/components/ExpertAvatarPicker", () => ({
  default: () => null,
}));
vi.mock("../pages/Agent/Workspace/components/WorkspaceDrawer", () => ({
  default: () => null,
}));
vi.mock("../pages/Agent/Skills/skillDisplayNames", () => ({
  useSkillDisplayName: () => (skill: { name: string }) => skill.name,
}));

vi.mock("../pages/Experts/components/ExpertComposerDefaultsFields", () => ({
  default: () => null,
}));

vi.mock("../pages/Chat/hooks/useWelcomeQuickCardsLayout", () => ({
  useWelcomeQuickCardsLayout: () => ({
    welcomeRef: { current: null },
    headingRef: { current: null },
    sectionTitleRef: { current: null },
    probeRef: { current: null },
    expanded: false,
    setExpanded: vi.fn(),
    cards: [],
    showToggle: false,
    autoHideMascot: false,
  }),
}));

import AgentProfileDrawer from "./AgentProfileDrawer";

const team = {
  agent_id: "team-1",
  name: "Research crew",
  kind: "team",
  state: "running",
} as OctopAgent;

async function select(label: string, text: string) {
  fireEvent.mouseDown(screen.getByLabelText(label));
  fireEvent.click(
    await screen.findByText(text, {
      selector: ".ant-select-item-option-content",
    }),
  );
}

async function openMember(index = 0) {
  const buttons = await screen.findAllByRole("button", {
    name: "chat.agentProfile.configureMember",
  });
  fireEvent.click(buttons[index]);
  await screen.findByLabelText("experts.defaultModelLabel");
}

function EntryFixture() {
  const [selected, setSelected] = useState<OctopAgent | null>(null);
  const [configure, setConfigure] = useState(false);
  const location = useLocation();
  const open = (id?: string, direct = false) => {
    setSelected(state.agents.find((agent) => agent.agent_id === id) ?? team);
    setConfigure(direct);
  };
  return (
    <>
      <output>{location.pathname}</output>
      <WelcomeScreen
        quickCards={[]}
        onPromptClick={vi.fn()}
        onConfigure={() => open("expert-0", true)}
      />
      <ProjectRoomBar
        teamId="team-1"
        onMention={vi.fn()}
        onConfigureMember={(id) => open(id, true)}
      />
      <ChatAgentProfileProvider canOpen isTeam onOpen={(id) => open(id)}>
        <ExpertMessageAvatar name="Writer message" profileAgentId="expert-0" />
      </ChatAgentProfileProvider>
      <AgentProfileDrawer
        open={selected !== null}
        agent={selected}
        configureDefaults={configure}
        onClose={() => setSelected(null)}
      />
    </>
  );
}

describe("chat member expert defaults", () => {
  const computedStyle = window.getComputedStyle;
  beforeEach(() => {
    vi.spyOn(window, "getComputedStyle").mockImplementation((element) =>
      computedStyle(element),
    );
    state.agents = ["Writer", "Analyst"].map(
      (name, index) =>
        ({
          agent_id: `expert-${index}`,
          name,
          kind: "expert",
          state: "running",
          is_owner: index === 0,
          is_shared: index === 1,
          user_id: index === 0 ? 7 : 8,
          default_model: "provider/old",
          config: { backend: { type: "local" }, keep: "original" },
        }) as OctopAgent,
    );
    state.patch.mockReset();
    state.refresh.mockReset();
    state.setActiveAgent.mockReset();
    state.failSave = false;
    state.failLoad = false;
  });

  it("opens the selected member, persists model/device, refreshes summaries and keeps the room", async () => {
    const closeProfile = vi.fn();
    render(
      <App>
        <AgentProfileDrawer open agent={team} onClose={closeProfile} />
      </App>,
    );
    await openMember();
    expect(
      screen.getByText("Writer · chat.agentProfile.configureDefaults"),
    ).toBeInTheDocument();
    await select("experts.defaultModelLabel", "provider / new");
    await select("experts.deviceBindingLabel", "Laptop");
    state.agents[0].config.keep = "changed elsewhere";
    state.agents[0].config.new_setting = true;
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));
    await waitFor(() =>
      expect(state.patch).toHaveBeenCalledWith("expert-0", {
        default_model: "provider/new",
        config: {
          backend: { type: "local" },
          keep: "changed elsewhere",
          new_setting: true,
          device_binding: { target_kind: "device", device_id: "laptop" },
        },
      }),
    );
    await waitFor(() =>
      expect(
        screen.queryByText("Writer · chat.agentProfile.configureDefaults"),
      ).not.toBeInTheDocument(),
    );
    expect(state.refresh).toHaveBeenCalledWith({ silent: true, force: true });
    expect(
      await screen.findByText(
        /defaultDevice.*laptop.*defaultModel.*provider\/new/,
      ),
    ).toBeInTheDocument();
    expect(state.agents[1].default_model).toBe("provider/old");
    expect(closeProfile).not.toHaveBeenCalled();
    expect(state.setActiveAgent).not.toHaveBeenCalled();
    // Returning to the member list lets the user select another expert without leaving chat.
    await openMember(1);
    expect(
      screen.getByText("Analyst · chat.agentProfile.configureDefaults"),
    ).toBeInTheDocument();
    expect(
      screen.getByText("chat.agentProfile.defaultsReadOnly"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "common.save" }),
    ).not.toBeInTheDocument();
    expect(screen.getByLabelText("experts.defaultModelLabel")).toBeDisabled();
  });

  it("only patches the edited model and keeps save errors open for retry", async () => {
    render(
      <App>
        <AgentProfileDrawer open agent={state.agents[0]} onClose={vi.fn()} />
      </App>,
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "chat.agentProfile.configureDefaults",
      }),
    );
    await screen.findByLabelText("experts.defaultModelLabel");
    await select("experts.defaultModelLabel", "provider / new");
    state.failSave = true;
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));
    expect(await screen.findByText("Save failed")).toBeInTheDocument();
    expect(state.patch).toHaveBeenLastCalledWith("expert-0", {
      default_model: "provider/new",
    });
    expect(state.refresh).not.toHaveBeenCalled();
    expect(
      screen.getByText("Writer · chat.agentProfile.configureDefaults"),
    ).toBeInTheDocument();
    state.failSave = false;
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));
    await waitFor(() => expect(state.refresh).toHaveBeenCalled());
  });

  it("does not PATCH untouched defaults or change the current room on cancel", async () => {
    const closeProfile = vi.fn();
    render(
      <App>
        <AgentProfileDrawer open agent={team} onClose={closeProfile} />
      </App>,
    );
    await openMember();
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));
    await waitFor(() =>
      expect(
        screen.queryByText("Writer · chat.agentProfile.configureDefaults"),
      ).not.toBeInTheDocument(),
    );
    expect(state.patch).not.toHaveBeenCalled();
    await openMember();
    fireEvent.click(screen.getByRole("button", { name: "common.cancel" }));
    expect(closeProfile).not.toHaveBeenCalled();
    expect(state.setActiveAgent).not.toHaveBeenCalled();
  });
  it("confirms dirty defaults before opening full settings in the same drawer", async () => {
    render(
      <App>
        <AgentProfileDrawer open agent={team} onClose={vi.fn()} />
      </App>,
    );
    await openMember();
    await select("experts.defaultModelLabel", "provider / new");
    fireEvent.click(
      screen.getByRole("button", { name: "chat.agentProfile.fullSettings" }),
    );
    expect(
      (await screen.findAllByText("chat.agentProfile.discardDefaults"))[0],
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getAllByRole("button", { name: "common.cancel" }).at(-1)!,
    );
    expect(
      screen.getByText("Writer · chat.agentProfile.configureDefaults"),
    ).toBeInTheDocument();
    fireEvent.click(
      screen.getByRole("button", { name: "chat.agentProfile.fullSettings" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "common.confirm" }),
    );
    expect(await screen.findByLabelText("experts.agentName")).toHaveValue(
      "Writer",
    );
    expect(state.patch).not.toHaveBeenCalled();
    expect(state.setActiveAgent).not.toHaveBeenCalled();
  });

  it("blocks save when detail loading fails and allows a retry", async () => {
    render(
      <App>
        <AgentProfileDrawer open agent={team} onClose={vi.fn()} />
      </App>,
    );
    const buttons = await screen.findAllByRole("button", {
      name: "chat.agentProfile.configureMember",
    });
    state.failLoad = true;
    fireEvent.click(buttons[0]);
    expect(await screen.findByText("Load failed")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "common.save" }),
    ).not.toBeInTheDocument();
    expect(state.patch).not.toHaveBeenCalled();
    state.failLoad = false;
    fireEvent.click(screen.getByRole("button", { name: "common.retry" }));
    expect(
      await screen.findByLabelText("experts.defaultModelLabel"),
    ).toBeInTheDocument();
  });
  it("opens the actual member-avatar menu configuration and message avatar without navigating", async () => {
    render(
      <MemoryRouter initialEntries={["/chat/team-1"]}>
        <App>
          <EntryFixture />
        </App>
      </MemoryRouter>,
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "octopus.members" }),
    );
    fireEvent.click(
      await screen.findByRole("button", { name: /Writer.*octopus.idle/ }),
    );
    fireEvent.click(await screen.findByText("octopus.configuration"));
    expect(
      await screen.findByText("Writer · chat.agentProfile.configureDefaults"),
    ).toBeInTheDocument();
    await select("experts.defaultModelLabel", "provider / new");
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));
    await waitFor(() =>
      expect(state.patch).toHaveBeenCalledWith("expert-0", {
        default_model: "provider/new",
      }),
    );
    expect(screen.getByText("/chat/team-1")).toBeInTheDocument();
    expect(state.setActiveAgent).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fireEvent.click(screen.getByRole("button", { name: "Writer message" }));
    fireEvent.click(
      await screen.findByRole("button", {
        name: "chat.agentProfile.configureDefaults",
      }),
    );
    expect(
      await screen.findByText("Writer · chat.agentProfile.configureDefaults"),
    ).toBeInTheDocument();
    expect(screen.getByText("/chat/team-1")).toBeInTheDocument();
  }, 15000);

  it("uses loaded ownership when the member began as a conservative fallback", async () => {
    const fallback = { ...state.agents[0], is_owner: false };
    render(
      <App>
        <AgentProfileDrawer open agent={fallback} onClose={vi.fn()} />
      </App>,
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: "chat.agentProfile.configureDefaults",
      }),
    );
    await screen.findByLabelText("experts.defaultModelLabel");
    expect(screen.getByRole("button", { name: "common.save" })).toBeEnabled();
    await select("experts.defaultModelLabel", "provider / new");
    fireEvent.click(screen.getByRole("button", { name: "common.save" }));
    await waitFor(() =>
      expect(state.patch).toHaveBeenCalledWith("expert-0", {
        default_model: "provider/new",
      }),
    );
  });
  it("opens quick defaults directly from the welcome assistant avatar configuration menu", async () => {
    render(
      <MemoryRouter initialEntries={["/chat/team-1"]}>
        <App>
          <EntryFixture />
        </App>
      </MemoryRouter>,
    );
    fireEvent.click(
      screen.getByRole("button", { name: "octopus.configuration" }),
    );
    fireEvent.click(
      await screen.findByRole("menuitem", { name: "octopus.configuration" }),
    );
    expect(
      await screen.findByText("Writer · chat.agentProfile.configureDefaults"),
    ).toBeInTheDocument();
    expect(
      await screen.findByLabelText("experts.defaultModelLabel"),
    ).toBeEnabled();
    expect(screen.getByText("/chat/team-1")).toBeInTheDocument();
    expect(state.setActiveAgent).not.toHaveBeenCalled();
  });
});
