import { act, fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  executionApi,
  type ExecutionContext,
  type ExecutionTarget,
} from "../../api/modules/execution";
import NativeDeviceFiles from "./NativeDeviceFiles";
import { sha256 } from "./helpers";
vi.mock("../../api/modules/execution", () => ({
  executionApi: { call: vi.fn(), createContext: vi.fn() },
}));
vi.mock("../Agent/Workspace/components/CodeEditor", () => ({
  default: ({
    value,
    onChange,
  }: {
    value: string;
    onChange: (value: string) => void;
  }) => (
    <textarea
      aria-label="Test code"
      value={value}
      onChange={(event) => onChange(event.target.value)}
    />
  ),
}));
vi.mock("../Chat/components/ResourcePanelContent", () => ({
  default: () => null,
}));
vi.mock("./NativeFileTransfers", () => ({ default: () => null }));
const context: ExecutionContext = {
  context_id: "ctx",
  device_id: "files",
  working_dir: "D:/samples",
  work_mode: "agentic",
  policy_revision: 1,
  grant_version: 1,
};
const device = {
  device_id: "files",
  name: "Files",
  platform: "windows",
  permissions: ["files_read", "files_write"],
  capabilities: [],
  policy_revision: 1,
  grant_version: 1,
} as ExecutionTarget;
describe("native directory request states", () => {
  it("returns to the same file paths after entering a child directory", async () => {
    vi.mocked(executionApi.call).mockImplementation(
      async (_ctx, action, params) => {
        if (action !== "fs.list") throw new Error("unexpected action");
        const path = params.path as string;
        return {
          path,
          entries:
            path === "D:/samples"
              ? [
                  {
                    name: "workspace",
                    path: "D:/samples/workspace",
                    is_dir: true,
                  },
                ]
              : [],
          next_offset: null,
        };
      },
    );
    render(
      <NativeDeviceFiles
        device={device}
        executionContext={context}
        onError={vi.fn()}
      />,
    );
    fireEvent.click(await screen.findByRole("button", { name: "workspace" }));
    await screen.findByText("devices.emptyDirectory");
    fireEvent.click(
      screen.getByRole("button", { name: "devices.native.parent" }),
    );
    await screen.findByRole("button", { name: "workspace" });
    expect(executionApi.call).toHaveBeenLastCalledWith("ctx", "fs.list", {
      path: "D:/samples",
      offset: 0,
    });
  });

  it("compares actual remote bytes after an opaque save failure without losing the draft", async () => {
    const original = "original\n";
    const remote = "external change\n";
    const hash = await sha256(new TextEncoder().encode(original));
    let reads = 0;
    vi.mocked(executionApi.call).mockImplementation(async (_ctx, action) => {
      if (action === "fs.list")
        return {
          path: "D:/samples",
          entries: [
            { name: "test.py", path: "D:/samples/test.py", is_dir: false },
          ],
          next_offset: null,
        };
      if (action === "fs.stat") return { size: original.length, sha256: hash };
      if (action === "fs.read")
        return {
          path: "D:/samples/test.py",
          data_b64: btoa(reads++ ? remote : original),
          eof: true,
          size: original.length,
        };
      throw new Error("opaque device operation error");
    });
    render(
      <NativeDeviceFiles
        device={device}
        executionContext={context}
        onError={vi.fn()}
      />,
    );
    fireEvent.click(await screen.findByText("test.py"));
    const editor = await screen.findByRole("textbox", { name: "Test code" });
    fireEvent.change(editor, { target: { value: "local draft\n" } });
    fireEvent.click(
      screen.getByRole("button", { name: "devices.native.save" }),
    );
    expect(await screen.findByText("external change")).toBeInTheDocument();
    expect(editor).toHaveValue("local draft\n");
  });
  it("does not present pending or failed reads as an empty directory, and retries successfully", async () => {
    let reject!: (error: Error) => void;
    vi.mocked(executionApi.call).mockImplementationOnce(
      () =>
        new Promise((_yes, no) => {
          reject = no;
        }),
    );
    const onError = vi.fn();
    render(
      <NativeDeviceFiles
        device={device}
        executionContext={context}
        onError={onError}
      />,
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.queryByText("devices.emptyDirectory")).toBeNull();
    await act(async () => {
      reject(new Error("directory read failed"));
      await Promise.resolve();
    });
    expect(onError).toHaveBeenCalledOnce();
    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByText("devices.emptyDirectory")).toBeNull();
    vi.mocked(executionApi.call).mockResolvedValueOnce({
      path: "D:/samples",
      entries: [
        {
          name: "example.py",
          path: "D:/samples/example.py",
          is_dir: false,
          size: 20,
        },
      ],
      next_offset: null,
    });
    fireEvent.click(screen.getByRole("button", { name: "common.refresh" }));
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByText("example.py")).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(executionApi.call).toHaveBeenLastCalledWith("ctx", "fs.list", {
      path: "D:/samples",
      offset: 0,
    });
  });
  it("shows empty only after a successful empty listing", async () => {
    vi.mocked(executionApi.call).mockResolvedValueOnce({
      path: "D:/samples",
      entries: [],
      next_offset: null,
    });
    render(
      <NativeDeviceFiles
        device={device}
        executionContext={context}
        onError={vi.fn()}
      />,
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(screen.getByText("devices.emptyDirectory")).toBeInTheDocument();
  });
});
