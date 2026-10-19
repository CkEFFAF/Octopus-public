import { describe, expect, it, vi, beforeEach } from "vitest";
import {
  render,
  screen,
  fireEvent,
  act,
  waitFor,
} from "@testing-library/react";
import { createRef } from "react";
import { App } from "antd";
import {
  saveWithdrawnDraft,
  readWithdrawnDraft,
} from "../utils/withdrawnDraft";
const attachmentSpies = vi.hoisted(() => ({ restore: vi.fn() }));

vi.mock("../../../hooks/useIsMobile", () => ({
  useIsMobile: () => false,
}));

vi.mock("../../../hooks/useSlashCommands", () => ({
  useSlashCommands: () => ({
    commands: [],
    labelFor: (cmd: string) => cmd,
  }),
}));

vi.mock("../../../hooks/useVoiceInput", () => ({
  useVoiceInput: () => ({
    recording: false,
    transcribing: false,
    toggle: vi.fn(),
  }),
}));

vi.mock("../../../hooks/useKeepInVisualViewport", () => ({
  useKeepInVisualViewport: () => undefined,
}));

vi.mock("../../../hooks/viewport", () => ({
  isPwaDisplay: () => false,
  needsComposerVisualViewportFix: () => false,
}));

vi.mock("../hooks/useChatAttachments", () => ({
  useChatAttachments: () => ({
    attachments: [],
    uploading: false,
    dragOver: false,
    fileInputRef: { current: null },
    handleFileSelect: vi.fn(),
    handleFileChange: vi.fn(),
    removeAttachment: vi.fn(),
    clearAttachments: vi.fn(),
    restoreAttachments: attachmentSpies.restore,
    handlePaste: vi.fn(),
    handleDragEnter: vi.fn(),
    handleDragLeave: vi.fn(),
    handleDragOver: vi.fn(),
    handleDrop: vi.fn(),
  }),
}));

vi.mock("../hooks/chatStore", () => ({
  consumePendingPrefillAttachments: () => [],
  readInputDraft: (agentId: string) =>
    agentId === "agent-2" ? "target expert draft" : "",
  writeInputDraft: vi.fn(),
}));

vi.mock("./ChatInputPreviewBar", () => ({
  default: () => null,
}));

vi.mock("./ChatInputActionsRow", () => ({
  default: ({
    onSubmit,
    canSend,
  }: {
    onSubmit: () => void;
    canSend: boolean;
  }) => (
    <button type="button" disabled={!canSend} onClick={onSubmit}>
      send
    </button>
  ),
}));

vi.mock("./ChatQueuedMessages", () => ({
  default: ({
    onReclaim,
    disabled,
  }: {
    onReclaim: (id: string) => void;
    disabled: boolean;
  }) => (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onReclaim("queued-id")}
    >
      withdraw
    </button>
  ),
}));

vi.mock("./SlashCommandMenu", () => ({
  default: () => null,
}));

vi.mock("./MentionPickerMenu", () => ({
  default: () => null,
  buildMentionItems: () => [],
}));

vi.mock("../hooks/useSlashMentionInput", () => ({
  useSlashMentionInput: ({
    text,
    setText,
    onSubmitRef,
  }: {
    text: string;
    setText: (v: string) => void;
    onSubmitRef: { current: () => void };
  }) => ({
    slashMenuOpen: false,
    slashMenuIndex: 0,
    setSlashMenuIndex: vi.fn(),
    mentionMenuOpen: false,
    mentionMenuIndex: 0,
    setMentionMenuIndex: vi.fn(),
    mentionQuery: "",
    mentionAgents: [],
    slashMenuFlat: [],
    slashMenuGroups: [],
    slashPickerGroups: [],
    slashMenuItems: [],
    mentionItems: [],
    filesLoading: false,
    filesError: null,
    runSlashCommand: vi.fn(),
    matchSlashCommand: () => null,
    handleMentionSelect: vi.fn(),
    handleSlashSelect: vi.fn(),
    handleTextChange: setText,
    handleKeyDown: (e: { key: string; preventDefault: () => void }) => {
      if (e.key === "Enter" && !e.preventDefault) return;
      void text;
      void onSubmitRef;
    },
  }),
}));

import ChatInput, { type ChatInputHandle } from "./ChatInput";

beforeEach(() => {
  vi.clearAllMocks();
});

describe("ChatInput prefill clear-on-send", () => {
  it("asks before recovering a withdrawn message over an existing draft on mount", async () => {
    saveWithdrawnDraft("recovery-agent", "mount", {
      id: "recovered",
      text: "withdrawn message",
      createdAt: 1,
    });
    render(
      <App>
        <ChatInput
          onSend={vi.fn()}
          onCancel={vi.fn()}
          onNewChat={vi.fn()}
          isStreaming
          agentId="recovery-agent"
          threadId="mount"
          initialText="keep my draft"
        />
      </App>,
    );
    expect(screen.getByRole("textbox")).toHaveValue("keep my draft");
    await waitFor(() =>
      expect(
        screen.getByRole("dialog", {
          name: "chat.queue.reclaimOverwriteTitle",
        }),
      ).toBeVisible(),
    );
    fireEvent.click(screen.getByRole("button", { name: /确.*认/ }));
    expect(screen.getByRole("textbox")).toHaveValue("withdrawn message");
    expect(readWithdrawnDraft("recovery-agent", "mount")).toBeNull();
  });

  it("keeps recovery and both drafts intact if the confirmation is accepted after changing threads", async () => {
    saveWithdrawnDraft("recovery-agent", "stale-modal", {
      id: "recovered",
      text: "withdrawn message",
      createdAt: 1,
    });
    const props = {
      onSend: vi.fn(),
      onCancel: vi.fn(),
      onNewChat: vi.fn(),
      isStreaming: true,
      agentId: "recovery-agent",
    };
    const view = render(
      <App>
        <ChatInput
          {...props}
          threadId="stale-modal"
          initialText="keep my draft"
        />
      </App>,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("dialog", {
          name: "chat.queue.reclaimOverwriteTitle",
        }),
      ).toBeVisible(),
    );
    view.rerender(
      <App>
        <ChatInput {...props} threadId="another" />
      </App>,
    );
    fireEvent.click(screen.getByRole("button", { name: /确.*认/ }));
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(readWithdrawnDraft("recovery-agent", "stale-modal")?.text).toBe(
      "withdrawn message",
    );
  });
  it("restores a withdrawal that finishes after the same conversation is reopened", async () => {
    let resolve!: (value: {
      id: string;
      text: string;
      createdAt: number;
      attachments: never[];
    }) => void;
    const onReclaimQueued = vi.fn(
      () =>
        new Promise<{
          id: string;
          text: string;
          createdAt: number;
          attachments: never[];
        }>((done) => {
          resolve = done;
        }),
    );
    const props = {
      onSend: vi.fn(),
      onCancel: vi.fn(),
      onNewChat: vi.fn(),
      isStreaming: true,
      onReclaimQueued,
      agentId: "agent-1",
      threadId: "reopened",
    };
    const first = render(<ChatInput {...props} />);
    fireEvent.click(screen.getByRole("button", { name: "withdraw" }));
    first.unmount();
    render(<ChatInput {...props} />);
    const attachments = [
      { filename: "paper.pdf", url: "/synthetic/paper.pdf" },
    ] as never[];
    await act(async () =>
      resolve({
        id: "queued-id",
        text: "late withdrawal",
        createdAt: 1,
        attachments,
      }),
    );
    expect(screen.getByRole("textbox")).toHaveValue("late withdrawal");
    expect(attachmentSpies.restore).toHaveBeenCalledWith(attachments);
  });
  it("restores withdrawn attachments only to their original conversation after navigating away", async () => {
    let resolve!: (value: {
      id: string;
      text: string;
      createdAt: number;
      attachments: never[];
    }) => void;
    const onReclaimQueued = vi.fn(
      () =>
        new Promise<{
          id: string;
          text: string;
          createdAt: number;
          attachments: never[];
        }>((done) => {
          resolve = done;
        }),
    );
    const props = {
      onSend: vi.fn(),
      onCancel: vi.fn(),
      onNewChat: vi.fn(),
      isStreaming: true,
      onReclaimQueued,
      agentId: "agent-1",
    };
    const { rerender } = render(<ChatInput {...props} threadId="original" />);
    fireEvent.click(screen.getByRole("button", { name: "withdraw" }));
    rerender(<ChatInput {...props} threadId="other" />);
    const attachments = [
      { filename: "paper.pdf", url: "/synthetic/paper.pdf" },
    ] as never[];
    await act(async () =>
      resolve({
        id: "queued-id",
        text: "original message",
        createdAt: 1,
        attachments,
      }),
    );
    expect(screen.getByRole("textbox")).toHaveValue("");
    expect(attachmentSpies.restore).not.toHaveBeenCalledWith(attachments);
    rerender(<ChatInput {...props} threadId="original" />);
    expect(screen.getByRole("textbox")).toHaveValue("original message");
    expect(attachmentSpies.restore).toHaveBeenCalledWith(attachments);
  });
  it("locks the draft during withdrawal so a delayed response cannot overwrite new edits", async () => {
    let resolve!: (value: {
      id: string;
      text: string;
      createdAt: number;
    }) => void;
    const onReclaimQueued = vi.fn(
      () =>
        new Promise<{ id: string; text: string; createdAt: number }>((done) => {
          resolve = done;
        }),
    );
    render(
      <ChatInput
        onSend={vi.fn()}
        onCancel={vi.fn()}
        onNewChat={vi.fn()}
        isStreaming
        onReclaimQueued={onReclaimQueued}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: "withdraw" }));
    expect(screen.getByRole("textbox")).toBeDisabled();
    fireEvent.change(screen.getByRole("textbox"), {
      target: { value: "must not overwrite" },
    });
    fireEvent.click(screen.getByRole("button", { name: "withdraw" }));
    expect(onReclaimQueued).toHaveBeenCalledOnce();
    await act(async () =>
      resolve({ id: "queued-id", text: "restored text", createdAt: 1 }),
    );
    expect(screen.getByRole("textbox")).toBeEnabled();
    expect(screen.getByRole("textbox")).toHaveValue("restored text");
  });
  it("queues a submitted draft by default while the agent runs", async () => {
    const onSend = vi.fn();
    const onQueue = vi.fn().mockResolvedValue("ok");
    const onSteerQueued = vi.fn();
    render(
      <ChatInput
        onSend={onSend}
        onQueue={onQueue}
        onSteerQueued={onSteerQueued}
        onCancel={vi.fn()}
        onNewChat={vi.fn()}
        isStreaming
        initialText="queue this"
      />,
    );
    await act(async () =>
      fireEvent.click(screen.getByRole("button", { name: "send" })),
    );
    expect(onQueue).toHaveBeenCalledOnce();
    expect(onQueue.mock.calls[0][0].text).toBe("queue this");
    expect(onSend).not.toHaveBeenCalled();
    expect(onSteerQueued).not.toHaveBeenCalled();
    expect(screen.getByRole("textbox")).toHaveValue("");
  });
  it("appends a member mention without losing the unsent draft", () => {
    const inputRef = createRef<ChatInputHandle>();
    render(
      <ChatInput
        ref={inputRef}
        onSend={vi.fn()}
        onCancel={vi.fn()}
        onNewChat={vi.fn()}
        isStreaming={false}
        isTeam
        agentId="agent-1"
        threadId="thread-1"
        initialText="请检查这个任务"
      />,
    );
    act(() => inputRef.current?.mentionExpert("Review Helper"));
    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe(
      "请检查这个任务 @Review-Helper ",
    );
  });
  it("does not restore stale initialText after send (skill-card prefill path)", async () => {
    // Mirrors welcome skill/quick-card flow:
    // 1) setPrefillText fills the composer imperatively while parent initialText
    //    is still ""
    // 2) parent keeps the prefill in a ref and re-passes it as initialText on
    //    the next render (e.g. after send updates chat state)
    // 3) composer must stay empty after send — not re-filled from that prop
    const onSend = vi.fn();
    const onCancel = vi.fn();
    const onNewChat = vi.fn();
    const inputRef = createRef<ChatInputHandle>();

    const { rerender } = render(
      <ChatInput
        ref={inputRef}
        onSend={onSend}
        onCancel={onCancel}
        onNewChat={onNewChat}
        isStreaming={false}
        initialText=""
        agentId="agent-1"
        threadId="thread-1"
      />,
    );

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    const prefill = "请填写收件人：";

    act(() => {
      inputRef.current?.setPrefillText(prefill);
    });
    expect(textarea.value).toBe(prefill);

    fireEvent.click(screen.getByRole("button", { name: "send" }));
    expect(onSend).toHaveBeenCalledWith(prefill, undefined);
    expect(textarea.value).toBe("");

    // Parent re-render still holding the prefill string in initialText
    rerender(
      <ChatInput
        ref={inputRef}
        onSend={onSend}
        onCancel={onCancel}
        onNewChat={onNewChat}
        isStreaming={true}
        initialText={prefill}
        agentId="agent-1"
        threadId="thread-1"
      />,
    );

    expect(textarea.value).toBe("");
  });

  it("clears parent prefill via onComposerCleared so edited text cannot be overwritten", () => {
    const onSend = vi.fn();
    const onCancel = vi.fn();
    const onNewChat = vi.fn();
    const inputRef = createRef<ChatInputHandle>();
    let parentPrefill = "";

    const { rerender } = render(
      <ChatInput
        ref={inputRef}
        onSend={onSend}
        onCancel={onCancel}
        onNewChat={onNewChat}
        isStreaming={false}
        initialText=""
        onComposerCleared={() => {
          parentPrefill = "";
        }}
        agentId="agent-1"
        threadId="thread-1"
      />,
    );

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    const prefill = "请填写收件人：";
    parentPrefill = prefill;

    act(() => {
      inputRef.current?.setPrefillText(prefill);
    });
    fireEvent.change(textarea, {
      target: { value: `${prefill}\n张三` },
    });

    fireEvent.click(screen.getByRole("button", { name: "send" }));
    expect(onSend).toHaveBeenCalledWith(`${prefill}\n张三`, undefined);
    expect(textarea.value).toBe("");
    expect(parentPrefill).toBe("");

    rerender(
      <ChatInput
        ref={inputRef}
        onSend={onSend}
        onCancel={onCancel}
        onNewChat={onNewChat}
        isStreaming={true}
        initialText={parentPrefill}
        onComposerCleared={() => {
          parentPrefill = "";
        }}
        agentId="agent-1"
        threadId="thread-1"
      />,
    );

    expect(textarea.value).toBe("");
  });

  it("restores the target agent draft instead of carrying stale prefill", () => {
    const props = {
      onSend: vi.fn(),
      onCancel: vi.fn(),
      onNewChat: vi.fn(),
      isStreaming: false,
      initialText: "previous expert prompt",
      threadId: null,
    };
    const { rerender } = render(<ChatInput {...props} agentId="agent-1" />);

    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textarea.value).toBe("previous expert prompt");

    rerender(<ChatInput {...props} agentId="agent-2" />);

    expect(textarea.value).toBe("target expert draft");
  });

  it("sends immediately in a team room while a turn is still streaming", () => {
    const onSend = vi.fn();
    const onQueue = vi.fn();
    render(
      <ChatInput
        onSend={onSend}
        onQueue={onQueue}
        onCancel={vi.fn()}
        onNewChat={vi.fn()}
        isStreaming
        isTeam
        agentId="team-1"
        threadId="thread-1"
      />,
    );
    const textarea = screen.getByRole("textbox") as HTMLTextAreaElement;
    fireEvent.change(textarea, { target: { value: "second question" } });
    fireEvent.click(screen.getByRole("button", { name: "send" }));
    expect(onSend).toHaveBeenCalledWith("second question", undefined);
    expect(onQueue).not.toHaveBeenCalled();
  });
});
