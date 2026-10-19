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

  it("defaults to queue on send while keeping stop available during generation", () => {
    render(
      <MemoryRouter>
        <ChatInputActionsRow
          {...baseProps}
          isStreaming
          canSend
          text="new question"
        />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByRole("button", { name: "chat.queue.action" }));
    expect(baseProps.onSubmit).toHaveBeenCalledOnce();
    expect(baseProps.onCancel).not.toHaveBeenCalled();
    expect(
      screen.queryByRole("button", { name: "chat.steer.action" }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Stop" })).toBeEnabled();
  });

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
    expect(screen.getByTestId("composer-model")).toHaveTextContent("Auto");
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

  it("keeps the current model directly selectable in a narrow desktop composer", async () => {
    vi.mocked(HTMLElement.prototype.getBoundingClientRect).mockReturnValue({
      ...document.body.getBoundingClientRect(),
      width: 440,
      right: 440,
    });
    render(
      <MemoryRouter>
        <ChatInputActionsRow
          {...baseProps}
          selectedModel="Provider/compact-model"
        />
      </MemoryRouter>,
    );

    const trigger = screen.getByTestId("composer-model");
    expect(trigger).toHaveTextContent("Compact Model");
    expect(trigger).toHaveAccessibleName("Model: Compact Model");
    fireEvent.click(trigger);
    fireEvent.click(await screen.findByText("Auto"));
    expect(baseProps.onModelChange).toHaveBeenCalledWith(null);
    expect(document.querySelector(".ant-drawer-content")).toBeNull();
  });

  it("keeps mobile model visible while other tools remain reachable in overflow", async () => {
    render(
      <MemoryRouter>
        <ChatInputActionsRow
          {...baseProps}
          isMobile
          defaultModel="Provider/compact-model"
          slashMenuItems={[shortcut]}
        />
      </MemoryRouter>,
    );
    expect(screen.getByTestId("composer-model")).toHaveTextContent(
      "Auto · Compact Model",
    );
    expect(
      screen.queryByLabelText("chatWelcome.newChat"),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByTestId("composer-plus"));
    expect(
      await screen.findByLabelText("chatWelcome.newChat"),
    ).toHaveTextContent("chatWelcome.newChat");
    expect(await screen.findByTestId("hitl-policy-picker")).toBeInTheDocument();
    fireEvent.click(await screen.findByText("快捷指令"));
    expect(await screen.findByTestId("composer-plus-panel")).toHaveTextContent(
      "/list",
    );
    expect(screen.queryByText("Model")).not.toBeInTheDocument();
  });

  it("starts a new compact chat from the more tools menu even without resource pickers", async () => {
    render(
      <MemoryRouter>
        <ChatInputActionsRow
          {...baseProps}
          isMobile
          availableModels={[]}
          onConversationModeChange={undefined}
          onHitlPolicyChange={undefined}
        />
      </MemoryRouter>,
    );
    fireEvent.click(screen.getByTestId("composer-plus"));
    fireEvent.click(
      await screen.findByRole("button", { name: "chatWelcome.newChat" }),
    );
    expect(baseProps.onNewChat).toHaveBeenCalledOnce();
  });

  it("updates the visible model after selection changes and resolves the automatic default", () => {
    const view = render(
      <MemoryRouter>
        <ChatInputActionsRow
          {...baseProps}
          defaultModel="Provider/compact-model"
        />
      </MemoryRouter>,
    );
    const trigger = () => screen.getByTestId("composer-model");
    expect(trigger()).toHaveTextContent("Auto · Compact Model");
    expect(trigger()).toHaveAttribute(
      "title",
      "Auto: Use agent default · Provider / Compact Model",
    );
    view.rerender(
      <MemoryRouter>
        <ChatInputActionsRow
          {...baseProps}
          selectedModel="Other/very-long-model-name"
        />
      </MemoryRouter>,
    );
    expect(trigger()).toHaveTextContent("very-long-model-name");
    expect(trigger()).toHaveAttribute("title", "Other/very-long-model-name");
    view.rerender(
      <MemoryRouter>
        <ChatInputActionsRow {...baseProps} defaultModel="compact-model" />
      </MemoryRouter>,
    );
    expect(trigger()).toHaveTextContent("Auto · Compact Model");
    view.rerender(
      <MemoryRouter>
        <ChatInputActionsRow {...baseProps} defaultModel="unknown-model" />
      </MemoryRouter>,
    );
    expect(trigger()).toHaveTextContent(/^Auto$/);
  });
});
