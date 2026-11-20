import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import MessageBubble from "./MessageBubble";
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
  it.each([
    ["user", 0],
    ["user", 1000],
    ["assistant", 0],
    ["assistant", 1000],
  ] as const)(
    "quotes a completed %s message with timestamp %s",
    (role, timestamp) => {
      const onQuote = vi.fn();
      const message = userMessage({
        role,
        timestamp,
        content: "A previous message\nwith a second line",
      });
      render(<MessageBubble message={message} onQuoteMessage={onQuote} />);

      fireEvent.click(screen.getByRole("button", { name: "chat.quote" }));

      expect(onQuote).toHaveBeenCalledOnce();
      expect(onQuote).toHaveBeenCalledWith(
        expect.objectContaining({
          id: message.id,
          role,
          content: "A previous message\nwith a second line",
        }),
      );
    },
  );

  it("quotes the visible answer without the hidden thinking text", () => {
    const onQuote = vi.fn();
    render(
      <MessageBubble
        message={userMessage({
          role: "assistant",
          content: "<think>Private reasoning</think>\nThe visible answer",
        })}
        onQuoteMessage={onQuote}
      />,
    );

    fireEvent.click(screen.getByRole("button", { name: "chat.quote" }));

    expect(onQuote).toHaveBeenCalledWith(
      expect.objectContaining({ content: "The visible answer" }),
    );
  });

  it.each([
    { status: "streaming" as const },
    { content: "" },
    { toolData: { name: "search", output: "tool output" } },
  ])(
    "does not offer a quote for unfinished or non-answer content %j",
    (extra) => {
      render(
        <MessageBubble
          message={userMessage({ role: "assistant", ...extra })}
          onQuoteMessage={vi.fn()}
        />,
      );

      expect(
        screen.queryByRole("button", { name: "chat.quote" }),
      ).not.toBeInTheDocument();
    },
  );

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
