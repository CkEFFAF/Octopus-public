import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import ChatDockGit from "./ChatDockGit";
import { request } from "../../../api/request";
import { showApiError } from "../../../utils/showApiToast";

vi.mock("react-i18next", () => ({
  useTranslation: () => ({
    t: (key: string, values?: { path?: string }) =>
      values?.path ? `${key}: ${values.path}` : key,
  }),
}));
vi.mock("../../../api/request", () => ({ request: vi.fn() }));
vi.mock("../../../utils/showApiToast", () => ({ showApiError: vi.fn() }));

const snapshot = {
  available: true,
  repositories: ["project"],
  path: "project",
  status: " M note.txt",
  diff: "diff --git a/note.txt b/note.txt\n@@ -1 +1 @@\n-old text\n+new text",
  staged_diff:
    "diff --git a/note.txt b/note.txt\n@@ -1 +1 @@\n-old staged\n+staged text",
  restorable: [{ path: "note.txt", hash: "expected-hash" }],
};

beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(request).mockResolvedValue(snapshot);
});

describe("ChatDockGit", () => {
  it("matches quoted and Chinese file names to their diff and restore target", async () => {
    const user = userEvent.setup();
    vi.mocked(request).mockResolvedValue({
      ...snapshot,
      status: '## main\n M "note name.txt"\n M 说明.md\n',
      diff: "diff --git a/note name.txt b/note name.txt\n@@ -1 +1 @@\n-old\n+space change\ndiff --git a/说明.md b/说明.md\n@@ -1 +1 @@\n-old\n+中文修改",
      staged_diff: "",
      restorable: [{ path: "说明.md", hash: "hash" }],
    });
    render(<ChatDockGit agentId="agent-a" />);
    expect(await screen.findByText("space change")).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: /note name.txt/ }),
    ).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: /说明.md/ }));
    expect(screen.getByText("中文修改")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "chat.git.restore" }),
    ).toBeInTheDocument();
  });
  it("shows status and both diffs returned by the workspace Git API", async () => {
    const user = userEvent.setup();
    render(<ChatDockGit agentId="agent-a" />);

    expect(await screen.findByText("new text")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: /chat.git.view.all/ }));
    await user.click(
      await screen.findByRole("menuitem", { name: "chat.git.view.staged" }),
    );
    expect(screen.getByText("staged text")).toBeInTheDocument();
    expect(request).toHaveBeenCalledWith(
      "/agents/agent-a/workspace/git?repository=.",
      { cache: "no-store" },
    );
  });

  it("requires confirmation, posts the selected hash, then shows the recovery copy", async () => {
    const user = userEvent.setup();
    vi.mocked(request)
      .mockResolvedValueOnce(snapshot)
      .mockResolvedValueOnce({ recovery_copy: "recovery/note.txt" })
      .mockResolvedValueOnce({ ...snapshot, diff: "", restorable: [] });
    render(<ChatDockGit agentId="agent-a" />);

    await screen.findByText("new text");
    await user.click(screen.getByRole("button", { name: "chat.git.restore" }));
    expect(
      screen.getByText("chat.git.restoreConfirm: note.txt"),
    ).toBeInTheDocument();
    expect(request).toHaveBeenCalledTimes(1);

    const dialog = screen.getByRole("dialog");
    await user.click(dialog.querySelector("button.ant-btn-primary")!);

    await waitFor(() =>
      expect(request).toHaveBeenCalledWith(
        "/agents/agent-a/workspace/git/restore",
        {
          method: "POST",
          body: JSON.stringify({
            repository: "project",
            path: "note.txt",
            expected_hash: "expected-hash",
          }),
        },
      ),
    );
    expect(
      await screen.findByText("chat.git.recoveryCopy: recovery/note.txt"),
    ).toBeInTheDocument();
  });

  it("shows an empty state when no repository is available", async () => {
    vi.mocked(request).mockResolvedValue({
      available: false,
      repositories: [],
    });
    render(<ChatDockGit agentId="agent-a" />);

    expect(
      await screen.findByText("chat.git.noRepository"),
    ).toBeInTheDocument();
  });

  it("reports a failed diff refresh without offering stale restore actions", async () => {
    vi.mocked(request).mockRejectedValue(new Error("offline"));
    render(<ChatDockGit agentId="agent-a" />);

    await waitFor(() => expect(showApiError).toHaveBeenCalledTimes(1));
    expect(
      screen.queryByRole("button", { name: "chat.git.restore" }),
    ).toBeNull();
  });
});
