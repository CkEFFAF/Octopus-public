import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import {
  afterAll,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import {
  pinnedFilesApi,
  type PinnedFile,
  type PinnedFiles,
} from "../api/modules/pinnedFiles";
import { executionApi } from "../api/modules/execution";
import PinnedFilesPanel from "./PinnedFilesPanel";

vi.mock("react-i18next", () => {
  const t = (key: string, values?: { title?: string; count?: number }) => {
    if (key === "pinnedFiles.selectFile") return `Select ${values?.title}`;
    if (
      key === "pinnedFiles.deleteSelected" ||
      key === "pinnedFiles.deleteConfirmTitle" ||
      key === "pinnedFiles.selectedCount"
    )
      return `${key} (${values?.count})`;
    return key;
  };
  return { useTranslation: () => ({ t }) };
});
vi.mock("../hooks/useCurrentUser", () => ({
  useCurrentUser: () => ({ id: 7, role: "user" }),
}));
vi.mock("../api/modules/pinnedFiles", () => ({
  pinnedFilesApi: { get: vi.fn(), save: vi.fn() },
}));
vi.mock("../api/modules/devices", () => ({
  devicesApi: {
    list: vi.fn(async () => ({
      devices: [{ device_id: "gpu-box", name: "Research GPU" }],
    })),
  },
}));
vi.mock("../api/modules/execution", () => ({
  executionApi: { createContext: vi.fn() },
}));
vi.mock("../pages/Chat/components/FilePanelContent", () => ({
  default: ({ agentId, filePath }: { agentId: string; filePath: string }) => (
    <div data-testid="expert-editor">
      {agentId}:{filePath}
    </div>
  ),
}));
vi.mock("../pages/Chat/components/ExecutionWorkbench", () => ({
  default: ({ initialFilePath }: { initialFilePath: string }) => (
    <div data-testid="project-editor">{initialFilePath}</div>
  ),
}));

const manual: PinnedFile = {
  id: "manual",
  title: "Experiment manual",
  scope: "expert",
  path: ".octop/notes/experiment-playbook.md",
};
const project: PinnedFile = {
  id: "report",
  title: "Latest report",
  scope: "project",
  path: "reports/latest.md",
  target_kind: "device",
  device_id: "gpu-box",
  working_dir: "/research",
};
let stored: PinnedFiles;
const getComputedStyle = window.getComputedStyle;
beforeAll(() => {
  vi.spyOn(window, "getComputedStyle").mockImplementation((element) =>
    getComputedStyle(element),
  );
});
afterAll(() => vi.restoreAllMocks());
beforeEach(() => {
  vi.clearAllMocks();
  stored = { revision: 1, files: [manual, project] };
  vi.mocked(pinnedFilesApi.get).mockImplementation(async () =>
    structuredClone(stored),
  );
  vi.mocked(pinnedFilesApi.save).mockImplementation(async (_, value) => {
    stored = { ...structuredClone(value), revision: value.revision + 1 };
    return stored;
  });
  vi.mocked(executionApi.createContext).mockResolvedValue({
    context_id: "ctx",
    device_id: "gpu-box",
    working_dir: "/research",
    work_mode: "agentic",
    policy_revision: 1,
    grant_version: 1,
  });
});

describe("pinned expert files", () => {
  it("collapses the list without losing access to pinned files", async () => {
    render(<PinnedFilesPanel agentId="gpu" defaultCollapsed />);
    const title = screen.getByRole("button", { name: /pinnedFiles.title/ });
    await waitFor(() => expect(title).toHaveTextContent("2"));
    expect(title).toHaveAttribute("aria-expanded", "false");
    expect(screen.getByText(manual.title)).not.toBeVisible();
    expect(screen.queryByText(manual.path)).not.toBeInTheDocument();
    fireEvent.click(title);
    expect(screen.getByText(manual.title)).toBeVisible();
    fireEvent.click(screen.getByText(manual.title));
    expect(await screen.findByTestId("expert-editor")).toHaveTextContent(
      manual.path,
    );
  });

  it("opens a collapsed list when starting batch selection", async () => {
    render(<PinnedFilesPanel agentId="gpu" defaultCollapsed />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "pinnedFiles.delete" }),
      ).toBeEnabled(),
    );
    fireEvent.click(screen.getByRole("button", { name: "pinnedFiles.delete" }));
    expect(
      screen.getByRole("button", { name: /pinnedFiles.title/ }),
    ).toHaveAttribute("aria-expanded", "true");
    const checkbox = screen.getByRole("checkbox", {
      name: `Select ${manual.title}`,
    });
    expect(checkbox).toBeEnabled();
    fireEvent.click(checkbox);
    expect(checkbox).toBeChecked();
  });

  it("selects rows for batch removal without opening files or showing row delete buttons", async () => {
    render(<PinnedFilesPanel agentId="gpu" />);
    await screen.findByText(manual.title);
    const panel = screen.getByRole("region", { name: "pinnedFiles.title" });
    expect(
      within(panel).queryByRole("button", { name: "pinnedFiles.remove" }),
    ).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "pinnedFiles.delete" }));
    fireEvent.click(within(panel).getByText(manual.title));
    fireEvent.click(within(panel).getByText(project.title));
    expect(
      screen.getByRole("checkbox", { name: `Select ${manual.title}` }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: `Select ${project.title}` }),
    ).toBeChecked();
    expect(
      screen.getByRole("button", { name: "pinnedFiles.deleteSelected (2)" }),
    ).toBeEnabled();
    expect(screen.queryByTestId("expert-editor")).not.toBeInTheDocument();
    expect(screen.queryByTestId("project-editor")).not.toBeInTheDocument();
    expect(executionApi.createContext).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "pinnedFiles.cancelSelection" }),
    );
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(pinnedFilesApi.save).not.toHaveBeenCalled();
  });

  it("requires confirmation and removes only the selected pinned entries", async () => {
    render(<PinnedFilesPanel agentId="gpu" />);
    await screen.findByText(manual.title);
    fireEvent.click(screen.getByRole("button", { name: "pinnedFiles.delete" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: `Select ${manual.title}` }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "pinnedFiles.deleteSelected (1)" }),
    );
    let modal = screen.getByRole("dialog");
    await waitFor(() =>
      expect(
        within(modal).getByText("pinnedFiles.removeConfirm"),
      ).toBeVisible(),
    );
    expect(pinnedFilesApi.save).not.toHaveBeenCalled();
    fireEvent.click(
      within(modal).getByRole("button", {
        name: "pinnedFiles.cancelSelection",
      }),
    );
    expect(
      screen.getByRole("checkbox", { name: `Select ${manual.title}` }),
    ).toBeChecked();
    expect(pinnedFilesApi.save).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "pinnedFiles.deleteSelected (1)" }),
    );
    modal = screen.getByRole("dialog");
    fireEvent.click(
      within(modal).getByRole("button", {
        name: "pinnedFiles.deleteSelected (1)",
      }),
    );
    await waitFor(() =>
      expect(pinnedFilesApi.save).toHaveBeenCalledWith("gpu", {
        revision: 1,
        files: [project],
      }),
    );
    await waitFor(() =>
      expect(screen.queryByRole("checkbox")).not.toBeInTheDocument(),
    );
    const panel = screen.getByRole("region", { name: "pinnedFiles.title" });
    expect(within(panel).queryByText(manual.title)).not.toBeInTheDocument();
    expect(within(panel).getByText(project.title)).toBeVisible();
    expect(executionApi.createContext).not.toHaveBeenCalled();
  });

  it("selects all fifteen entries and clears them with one revision-checked write", async () => {
    stored.files = Array.from({ length: 15 }, (_, index) => ({
      ...manual,
      id: `pin-${index}`,
      title: `Manual ${index}`,
    }));
    render(<PinnedFilesPanel agentId="gpu" />);
    await screen.findByText("Manual 0");
    fireEvent.click(screen.getByRole("button", { name: "pinnedFiles.delete" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: "pinnedFiles.selectAll" }),
    );
    expect(screen.getAllByRole("checkbox")).toHaveLength(16);
    expect(
      screen
        .getAllByRole("checkbox")
        .every((checkbox) => (checkbox as HTMLInputElement).checked),
    ).toBe(true);
    fireEvent.click(
      screen.getByRole("button", { name: "pinnedFiles.deleteSelected (15)" }),
    );
    fireEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", {
        name: "pinnedFiles.deleteSelected (15)",
      }),
    );
    await waitFor(() =>
      expect(pinnedFilesApi.save).toHaveBeenCalledWith("gpu", {
        revision: 1,
        files: [],
      }),
    );
    expect(pinnedFilesApi.save).toHaveBeenCalledTimes(1);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "pinnedFiles.delete" }),
      ).toBeDisabled(),
    );
  });

  it("retains the refreshed list and selection after a CAS conflict", async () => {
    vi.mocked(pinnedFilesApi.save).mockRejectedValueOnce(
      new Error(
        '409 - {"error":{"details":{"reason":"pinned_files_conflict"}}}',
      ),
    );
    render(<PinnedFilesPanel agentId="gpu" />);
    await screen.findByText(manual.title);
    fireEvent.click(screen.getByRole("button", { name: "pinnedFiles.delete" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: `Select ${manual.title}` }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "pinnedFiles.deleteSelected (1)" }),
    );
    const concurrent = {
      ...manual,
      id: "concurrent",
      title: "New concurrent file",
    };
    stored = { revision: 2, files: [manual, project, concurrent] };
    const modal = screen.getByRole("dialog");
    fireEvent.click(
      within(modal).getByRole("button", {
        name: "pinnedFiles.deleteSelected (1)",
      }),
    );
    await waitFor(() =>
      expect(within(modal).getByText("pinnedFiles.conflict")).toBeVisible(),
    );
    expect(
      screen.getByRole("checkbox", { name: `Select ${manual.title}` }),
    ).toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: `Select ${project.title}` }),
    ).not.toBeChecked();
    expect(
      screen.getByRole("checkbox", { name: "Select New concurrent file" }),
    ).not.toBeChecked();
    expect(
      within(
        screen.getByRole("region", { name: "pinnedFiles.title" }),
      ).getByText(manual.title),
    ).toBeVisible();
    fireEvent.click(
      within(modal).getByRole("button", {
        name: "pinnedFiles.deleteSelected (1)",
      }),
    );
    await waitFor(() =>
      expect(pinnedFilesApi.save).toHaveBeenLastCalledWith("gpu", {
        revision: 2,
        files: [project, concurrent],
      }),
    );
  });

  it("clears selection and its confirmation when switching experts", async () => {
    const view = render(<PinnedFilesPanel agentId="old" />);
    await screen.findByText(manual.title);
    fireEvent.click(screen.getByRole("button", { name: "pinnedFiles.delete" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: `Select ${manual.title}` }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "pinnedFiles.deleteSelected (1)" }),
    );
    view.rerender(<PinnedFilesPanel agentId="new" />);
    await waitFor(() =>
      expect(screen.queryByRole("dialog")).not.toBeInTheDocument(),
    );
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "pinnedFiles.delete" }));
    expect(
      screen.getByRole("checkbox", { name: `Select ${manual.title}` }),
    ).not.toBeChecked();
    expect(pinnedFilesApi.save).not.toHaveBeenCalled();
  });

  it("blocks changes while loading and prevents duplicate batch writes while saving", async () => {
    let finishLoad!: (value: PinnedFiles) => void;
    vi.mocked(pinnedFilesApi.get).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finishLoad = resolve;
        }),
    );
    render(<PinnedFilesPanel agentId="gpu" />);
    expect(
      screen.getByRole("button", { name: "pinnedFiles.delete" }),
    ).toBeDisabled();
    expect(
      screen.getByRole("button", { name: "pinnedFiles.add" }),
    ).toBeDisabled();
    await act(async () => finishLoad(structuredClone(stored)));
    fireEvent.click(screen.getByRole("button", { name: "pinnedFiles.delete" }));
    fireEvent.click(
      screen.getByRole("checkbox", { name: `Select ${manual.title}` }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "pinnedFiles.deleteSelected (1)" }),
    );
    let finishSave!: () => void;
    const waiting = new Promise<void>((resolve) => {
      finishSave = resolve;
    });
    vi.mocked(pinnedFilesApi.save).mockImplementationOnce(async (_, value) => {
      await waiting;
      stored = { ...value, revision: value.revision + 1 };
      return stored;
    });
    const modal = screen.getByRole("dialog");
    const confirm = within(modal).getByRole("button", {
      name: "pinnedFiles.deleteSelected (1)",
    });
    fireEvent.click(confirm);
    fireEvent.click(confirm);
    expect(pinnedFilesApi.save).toHaveBeenCalledTimes(1);
    expect(confirm).toBeDisabled();
    expect(
      screen.getByRole("checkbox", { name: `Select ${manual.title}` }),
    ).toBeDisabled();
    expect(
      within(modal).getByRole("button", {
        name: "pinnedFiles.cancelSelection",
      }),
    ).toBeDisabled();
    await act(async () => finishSave());
    await waitFor(() =>
      expect(screen.queryByRole("checkbox")).not.toBeInTheDocument(),
    );
  });

  it("hides the owner's bookmarks from shared-expert visitors", async () => {
    vi.mocked(pinnedFilesApi.get).mockRejectedValue(
      new Error('403 - {"error":{"code":"FORBIDDEN"}}'),
    );
    render(<PinnedFilesPanel agentId="shared" />);
    await waitFor(() =>
      expect(
        screen.queryByRole("region", { name: "pinnedFiles.title" }),
      ).not.toBeInTheDocument(),
    );
  });
  it("loads across conversations and opens expert files in the editor", async () => {
    const view = render(<PinnedFilesPanel agentId="gpu" threadId="chat-a" />);
    fireEvent.click(await screen.findByText(manual.title));
    expect(await screen.findByTestId("expert-editor")).toHaveTextContent(
      `gpu:${manual.path}`,
    );
    expect(executionApi.createContext).not.toHaveBeenCalled();
    view.unmount();
    render(<PinnedFilesPanel agentId="gpu" threadId="chat-b" />);
    expect(await screen.findByText(manual.title)).toBeInTheDocument();
    expect(pinnedFilesApi.get).toHaveBeenLastCalledWith("gpu");
  });

  it("uses the pinned server instead of a conversation's current target", async () => {
    render(<PinnedFilesPanel agentId="gpu" threadId="chat-b" />);
    fireEvent.click(await screen.findByText(project.title));
    await waitFor(() =>
      expect(executionApi.createContext).toHaveBeenCalledWith({
        agent_id: "gpu",
        thread_id: "chat-b",
        target_kind: "device",
        device_id: "gpu-box",
        working_dir: "/research",
        work_mode: "agentic",
      }),
    );
    expect(await screen.findByTestId("project-editor")).toHaveTextContent(
      project.path,
    );
  });

  it("discards an opening file context when the conversation changes", async () => {
    let finish!: (
      value: Awaited<ReturnType<typeof executionApi.createContext>>,
    ) => void;
    vi.mocked(executionApi.createContext).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          finish = resolve;
        }),
    );
    const view = render(<PinnedFilesPanel agentId="gpu" threadId="chat-a" />);
    fireEvent.click(await screen.findByText(project.title));
    view.rerender(<PinnedFilesPanel agentId="gpu" threadId="chat-b" />);
    await act(async () =>
      finish({
        context_id: "old-context",
        device_id: "gpu-box",
        working_dir: "/research",
        work_mode: "agentic",
        policy_revision: 1,
        grant_version: 1,
      }),
    );
    expect(screen.queryByTestId("project-editor")).not.toBeInTheDocument();
  });

  it("edits the bookmark using its loaded revision", async () => {
    render(<PinnedFilesPanel agentId="gpu" />);
    await screen.findByText(manual.title);
    fireEvent.click(
      screen.getAllByRole("button", { name: "pinnedFiles.edit" })[0],
    );
    const modal = screen.getByRole("dialog");
    fireEvent.change(within(modal).getByLabelText("pinnedFiles.label"), {
      target: { value: "Updated manual" },
    });
    fireEvent.click(within(modal).getByRole("button", { name: /OK|确定/ }));
    await waitFor(() =>
      expect(pinnedFilesApi.save).toHaveBeenCalledWith("gpu", {
        revision: 1,
        files: [{ ...manual, title: "Updated manual" }, project],
      }),
    );
    expect(await screen.findByText("Updated manual")).toBeInTheDocument();
  });

  it("keeps the edit draft after a concurrent list change", async () => {
    vi.mocked(pinnedFilesApi.save).mockRejectedValue(
      new Error(
        '409 - {"error":{"details":{"reason":"pinned_files_conflict"}}}',
      ),
    );
    render(<PinnedFilesPanel agentId="gpu" />);
    await screen.findByText(manual.title);
    fireEvent.click(
      screen.getAllByRole("button", { name: "pinnedFiles.edit" })[0],
    );
    const modal = screen.getByRole("dialog");
    fireEvent.change(within(modal).getByLabelText("pinnedFiles.label"), {
      target: { value: "Unsaved manual" },
    });
    fireEvent.click(within(modal).getByRole("button", { name: /OK|确定/ }));
    expect(
      await within(modal).findByText("pinnedFiles.conflict"),
    ).toBeInTheDocument();
    expect(within(modal).getByLabelText("pinnedFiles.label")).toHaveValue(
      "Unsaved manual",
    );
  });

  it("ignores a stale response after switching experts", async () => {
    let resolve!: (value: PinnedFiles) => void;
    vi.mocked(pinnedFilesApi.get).mockImplementationOnce(
      () =>
        new Promise((done) => {
          resolve = done;
        }),
    );
    const view = render(<PinnedFilesPanel agentId="old" />);
    view.rerender(<PinnedFilesPanel agentId="new" />);
    expect(await screen.findByText(manual.title)).toBeInTheDocument();
    await act(async () =>
      resolve({ revision: 3, files: [{ ...manual, title: "Wrong expert" }] }),
    );
    expect(screen.queryByText("Wrong expert")).not.toBeInTheDocument();
  });
});
