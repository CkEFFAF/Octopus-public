import { fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { ResolvedModel } from "../../../api/types";
import { resolveSlashIcon } from "../../../utils/slashIcons";
import ChatInputActionsRow from "./ChatInputActionsRow";

vi.mock("./ContextWindowRing", () => ({
  default: () => null,
}));

const models: ResolvedModel[] = [
  {
    provider_id: 1,
    provider_name: "Provider",
    provider_kind: "openai",
    model: "compact-model",
    name: "Compact Model",
    context_window: 128_000,
  },
];

const baseProps = {
  isMobile: false,
  isStreaming: false,
  canSend: false,
  text: "",
  polishing: false,
  uploading: false,
  recording: false,
  transcribing: false,
  availableModels: models,
  onModelChange: vi.fn(),
  onConversationModeChange: vi.fn(),
  onHitlPolicyChange: vi.fn(),
  slashPickerGroups: null,
  slashMenuItems: [],
  onSlashShortcutSelect: vi.fn(),
  onFileSelect: vi.fn(),
  onNewChat: vi.fn(),
  onPolish: vi.fn(),
  onToggleVoice: vi.fn(),
  onCancel: vi.fn(),
  onSubmit: vi.fn(),
};

const shortcut = {
  command: "/list",
  label: "List",
  icon: resolveSlashIcon("List"),
  tone: "blue" as const,
  spec: {
    name: "list",
    command: "/list",
    aliases: [],
    label_en: "List",
    label_zh: "列表",
    description_en: "List items",
    description_zh: "列出项目",
    usage: "/list",
    icon: "List",
    tone: "blue",
    category: "general",
    origins: ["ui"],
    client_action: "none",
  },
};

describe("ChatInputActionsRow responsive toolbar", () => {
  beforeEach(() => {
    vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
      width: 900,
      height: 40,
      x: 0,
      y: 0,
      top: 0,
      left: 0,
      right: 900,
      bottom: 40,
      toJSON: () => ({}),
    });
    vi.clearAllMocks();
  });

  afterEach(() => vi.restoreAllMocks());

  it("keeps available model and mode controls directly accessible on a wide toolbar", () => {
    render(
      <MemoryRouter>
        <ChatInputActionsRow {...baseProps} />
      </MemoryRouter>,
    );

    expect(screen.queryByTestId("composer-plus")).not.toBeInTheDocument();
    expect(screen.getByTestId("hitl-policy-picker")).toBeInTheDocument();
    expect(screen.queryByLabelText("快捷指令")).not.toBeInTheDocument();
    expect(screen.getByLabelText("Upload attachment")).toBeInTheDocument();
    expect(screen.getByTestId("composer-mode")).toBeInTheDocument();
    expect(screen.getByTestId("composer-model")).toHaveTextContent("Model");
  });

  it("hides the approval picker when HITL policy cannot be changed", () => {
    render(
      <MemoryRouter>
        <ChatInputActionsRow {...baseProps} onHitlPolicyChange={undefined} />
      </MemoryRouter>,
    );

    expect(screen.queryByTestId("hitl-policy-picker")).not.toBeInTheDocument();
    expect(screen.queryByLabelText("快捷指令")).not.toBeInTheDocument();
  });

  it("shows all configured pickers with labels and opens shortcuts directly on desktop", async () => {
    render(
      <MemoryRouter>
        <ChatInputActionsRow
          {...baseProps}
          availableConnectors={[]}
          onConnectorsChange={vi.fn()}
          availableKnowledgeBases={[]}
          onKnowledgeBaseIdsChange={vi.fn()}
          availableSkills={[]}
          onInsertSkillCommand={vi.fn()}
          availableExperts={[{ agent_id: "qa", name: "QA" }]}
          onInsertExpertMention={vi.fn()}
          availableSubagents={[{ slug: "qa", name: "QA", path: "agents/qa" }]}
          onInsertSubagentMention={vi.fn()}
          slashMenuItems={[shortcut]}
        />
      </MemoryRouter>,
    );

    for (const key of [
      "mode",
      "model",
      "connector",
      "knowledge",
      "skill",
      "expert",
      "subagent",
      "shortcut",
    ]) {
      const button = screen.getByTestId(`composer-${key}`);
      expect(button.textContent).not.toBe("");
      expect(button).toHaveAccessibleName();
    }
    expect(screen.queryByTestId("composer-plus")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("composer-shortcut"));
    const command = await screen.findByText("List");
    fireEvent.click(command);
    expect(baseProps.onSlashShortcutSelect).toHaveBeenCalledWith("/list");
  });

  it("uses the original model selection behavior from a direct desktop button", async () => {
    render(
      <MemoryRouter>
        <ChatInputActionsRow {...baseProps} />
      </MemoryRouter>,
    );

    fireEvent.click(screen.getByTestId("composer-model"));
    fireEvent.click(await screen.findByText("Provider / Compact Model"));
    expect(baseProps.onModelChange).toHaveBeenCalledWith(
      "Provider/compact-model",
    );
  });

  it("uses overflow for a narrow desktop composer even in a wide window", async () => {
    vi.mocked(HTMLElement.prototype.getBoundingClientRect).mockReturnValue({
      ...document.body.getBoundingClientRect(),
      width: 440,
      right: 440,
    });
    render(
      <MemoryRouter>
        <ChatInputActionsRow {...baseProps} />
      </MemoryRouter>,
    );

    expect(screen.queryByTestId("composer-model")).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("composer-plus"));
    expect(await screen.findByText("Model")).toBeInTheDocument();
    expect(screen.queryByTestId("composer-plus-panel")).not.toBeInTheDocument();

    fireEvent.click(screen.getByText("Model"));

    const panel = await screen.findByTestId("composer-plus-panel");
    expect(panel.querySelector("img")).not.toBeNull();
    const menu = document.querySelector("[class*='plusFlyoutMenu']");
    if (menu && menu.getBoundingClientRect().height > 0) {
      expect(Number.parseFloat(getComputedStyle(panel).maxHeight)).toBe(
        Math.round(menu.getBoundingClientRect().height),
      );
    }
    expect(document.querySelector(".ant-drawer-content")).toBeNull();
    expect(document.querySelector(".ant-popover")).toBeInTheDocument();
    expect(screen.getByText("Model")).toBeInTheDocument();
  });

  it("keeps mobile shortcuts reachable while mode and model stay in compact overflow", async () => {
    render(
      <MemoryRouter>
        <ChatInputActionsRow
          {...baseProps}
          isMobile
          slashMenuItems={[shortcut]}
        />
      </MemoryRouter>,
    );
    expect(screen.queryByTestId("composer-model")).not.toBeInTheDocument();
    expect(screen.getByLabelText("chatWelcome.newChat")).toBeInTheDocument();
    fireEvent.click(screen.getByTestId("composer-plus"));
    fireEvent.click(await screen.findByText("快捷指令"));
    expect(await screen.findByTestId("composer-plus-panel")).toHaveTextContent(
      "/list",
    );
    expect(screen.queryByText("Model")).not.toBeInTheDocument();
  });
});
