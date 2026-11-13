import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import MessageBubble, { ToolDetailsInline } from "./MessageBubble";
import type { ChatMessage } from "../hooks/useChat";
import type { OctopUser } from "../../../api/modules/auth";

const currentUser: Partial<OctopUser> = {
  username: "ada",
  display_name: "Ada",
  avatar_icon: "business",
  avatar_url: null,
};

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string) => key,
  }),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
}));

vi.mock("../../../hooks/useServerTimezone", () => ({
  useServerTimezone: () => "UTC",
}));

vi.mock("../../../hooks/useCurrentUser", () => ({
  useCurrentUser: () => currentUser,
}));

vi.mock("../../../hooks/useAuthImageSrc", () => ({
  useAuthImageSrc: (url: string) => ({
    src: url || "",
    loadState: url ? "ready" : "idle",
  }),
}));

vi.mock("../../../context/VoiceOutputContext", () => ({
  useVoiceOutputContext: () => ({ speakingId: null, speak: vi.fn() }),
}));

vi.mock("../../../context/AgentContext", () => ({
  useAgent: () => ({
    activeAgent: { agent_id: "host", name: "助手", icon_name: "bot" },
    agents: [],
  }),
}));

function userMessage(extra: Partial<ChatMessage> = {}): ChatMessage {
  return {
    id: extra.id ?? "u1",
    role: "user",
    content: extra.content ?? "hello there",
    status: "done",
    timestamp: Date.now(),
    ...extra,
  };
}

describe("MessageBubble user avatar", () => {
  it("shows the authenticated machine name instead of the current account", () => {
    render(
      <MessageBubble
        message={userMessage({
          sender: { kind: "machine", id: "key-1", name: "Codex" },
        })}
      />,
    );
    expect(screen.getByLabelText("Codex")).toBeInTheDocument();
    expect(screen.getByText("Codex")).toBeInTheDocument();
    expect(screen.queryByLabelText("Ada")).not.toBeInTheDocument();
  });
  it("shows ACP runner identity on an assistant response", () => {
    render(
      <MessageBubble
        message={userMessage({
          role: "assistant",
          sender: { kind: "acp", id: "runner", name: "GrokBot" },
        })}
      />,
    );
    expect(screen.getByLabelText("GrokBot")).toBeInTheDocument();
    expect(screen.getByText("GrokBot")).toBeInTheDocument();
    expect(screen.queryByLabelText("助手")).not.toBeInTheDocument();
  });
  it("localizes the preview mask for direct image attachments", () => {
    render(
      <MessageBubble
        message={userMessage({
          attachments: [
            {
              kind: "image",
              url: "https://example.test/chart.png",
              filename: "chart.png",
            },
          ],
        })}
      />,
    );
    expect(screen.getByText("common.preview")).toBeInTheDocument();
    expect(screen.queryByText("Preview")).not.toBeInTheDocument();
  });
  it("renders historical model failures as a recovery card without internal instructions", () => {
    const retry = vi.fn();
    render(
      <MessageBubble
        message={userMessage({
          role: "assistant",
          content:
            "[model_call_failed]\nThe model API request failed. Do not pretend success.\nTechnical detail: HTTP 402 insufficient_quota",
        })}
        onRegenerate={retry}
      />,
    );
    expect(
      screen.getByText("stream_errors.insufficient_balance"),
    ).toBeInTheDocument();
    expect(screen.queryByText(/Do not pretend/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "chat.retry" }),
    ).not.toBeInTheDocument();
    expect(retry).not.toHaveBeenCalled();
  });
  it("shows the account preset icon instead of name initials", () => {
    currentUser.avatar_icon = "business";
    currentUser.avatar_url = null;
    render(<MessageBubble message={userMessage()} showAvatar />);

    const sender = screen.getByLabelText("Ada");
    expect(sender.querySelector("svg")).toBeTruthy();
    expect(sender).not.toHaveTextContent("A");
  });

  it("shows the uploaded account photo when present", () => {
    currentUser.avatar_icon = "user";
    currentUser.avatar_url = "/api/users/7/avatar";
    render(<MessageBubble message={userMessage()} showAvatar />);

    const sender = screen.getByLabelText("Ada");
    expect(sender.querySelector("img")).toHaveAttribute(
      "src",
      "/api/users/7/avatar",
    );
    expect(sender.querySelector("svg")).toBeNull();
  });
});

it("keeps a real ACP child link accessible when the tool failed", () => {
  render(
    <ToolDetailsInline
      agentId="host"
      isStreaming={false}
      toolData={{
        name: "acp_runner",
        errorCode: "execution_failed",
        arguments: '{"runner":"codex"}',
        output: "ACP process failed",
        artifact: { collaboration_thread_id: "acp-child" },
      }}
    />,
  );
  expect(
    screen.getByRole("link", { name: "collaboration.viewConversation" }),
  ).toHaveAttribute("href", "/chat/host/acp-child");
  fireEvent.click(screen.getByRole("button", { expanded: false }));
  expect(screen.getByText(/ACP process failed/)).toBeInTheDocument();
});

it("keeps ACP permissions available alongside the child conversation link", () => {
  const onSelect = vi.fn();
  render(
    <ToolDetailsInline
      agentId="host"
      isStreaming={false}
      onAcpPermissionSelect={onSelect}
      toolData={{
        name: "acp_runner",
        arguments: '{"runner":"codex"}',
        output:
          "[permission_required] Approve access\n- Allow once (id=allow_once)",
        artifact: { collaboration_thread_id: "permission-child" },
      }}
    />,
  );
  expect(
    screen.getByRole("link", { name: "collaboration.viewConversation" }),
  ).toHaveAttribute("href", "/chat/host/permission-child");
  fireEvent.click(screen.getByRole("button", { expanded: false }));
  fireEvent.click(screen.getByRole("button", { name: "Allow once" }));
  expect(onSelect).toHaveBeenCalledWith(
    expect.stringContaining('message="allow_once"'),
  );
});
