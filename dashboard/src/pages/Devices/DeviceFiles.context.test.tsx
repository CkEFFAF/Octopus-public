import { act, fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { RestrictedDeviceFiles } from "./DeviceFiles";
import {
  executionApi,
  type ExecutionContext,
} from "../../api/modules/execution";
import { devicesApi } from "../../api/modules/devices";
vi.mock("../../api/modules/execution", () => ({
  executionApi: { call: vi.fn() },
}));
vi.mock("../../api/modules/devices", () => ({
  devicesApi: { call: vi.fn(), transfer: vi.fn() },
}));
vi.mock("./NativeDeviceFiles", () => ({ default: () => null }));
const device = {
  device_id: "restricted",
  name: "Shared",
  roots: [
    {
      id: "samples",
      name: "Samples",
      path: "D:/samples",
      read: true,
      write: true,
    },
  ],
  online: true,
  revoked_at: null,
  capabilities: ["files_read", "files_write"],
  permissions: ["files_read", "files_write"],
};
const context: ExecutionContext = {
  context_id: "first",
  device_id: "restricted",
  work_mode: "ask",
  working_dir: null,
  policy_revision: 1,
  grant_version: 1,
};
const props = { device, devices: [], onError: vi.fn(), onOperation: vi.fn() };
beforeEach(() => vi.clearAllMocks());
describe("restricted files in a request context", () => {
  it.each(["ask", "plan"] as const)(
    "uses files.list through the %s context and disables writes/transfer",
    async (mode) => {
      vi.mocked(executionApi.call).mockResolvedValueOnce({
        root_id: "samples",
        path: "",
        entries: [
          { name: "real.txt", path: "real.txt", is_dir: false, size: 3 },
        ],
      });
      render(
        <RestrictedDeviceFiles
          {...props}
          executionContext={{ ...context, work_mode: mode }}
        />,
      );
      await act(async () => {
        await Promise.resolve();
      });
      expect(screen.getByText("real.txt")).toBeInTheDocument();
      expect(executionApi.call).toHaveBeenLastCalledWith(
        "first",
        "files.list",
        { root_id: "samples", path: "" },
        expect.any(AbortSignal),
      );
      expect(devicesApi.call).not.toHaveBeenCalled();
      expect(
        screen.getByRole("button", { name: "devices.upload" }),
      ).toBeDisabled();
      expect(screen.queryByText("devices.transferTitle")).toBeNull();
    },
  );
  it("aborts and discards a previous context listing", async () => {
    let complete!: (value: unknown) => void;
    vi.mocked(executionApi.call).mockImplementationOnce(
      () =>
        new Promise((yes) => {
          complete = yes;
        }),
    );
    const { rerender } = render(
      <RestrictedDeviceFiles {...props} executionContext={context} />,
    );
    await act(async () => {
      await Promise.resolve();
    });
    const signal = vi.mocked(executionApi.call).mock.calls.at(-1)![3]!;
    vi.mocked(executionApi.call).mockResolvedValueOnce({
      entries: [
        { name: "current.txt", path: "current.txt", is_dir: false, size: 1 },
      ],
    });
    rerender(
      <RestrictedDeviceFiles
        {...props}
        executionContext={{ ...context, context_id: "second" }}
      />,
    );
    await act(async () => {
      await Promise.resolve();
      complete({
        entries: [{ name: "old.txt", path: "old.txt", is_dir: false, size: 1 }],
      });
      await Promise.resolve();
    });
    expect(signal.aborted).toBe(true);
    expect(screen.getByText("current.txt")).toBeInTheDocument();
    expect(screen.queryByText("old.txt")).toBeNull();
  });
  it("keeps the device page using the existing device endpoint", async () => {
    vi.mocked(devicesApi.call).mockResolvedValueOnce({
      root_id: "samples",
      path: "",
      entries: [],
    });
    render(<RestrictedDeviceFiles {...props} />);
    await act(async () => {
      await Promise.resolve();
    });
    expect(devicesApi.call).toHaveBeenLastCalledWith(
      "restricted",
      "files.list",
      { root_id: "samples", path: "" },
      expect.any(AbortSignal),
    );
    expect(
      screen.getByRole("button", { name: "devices.upload" }),
    ).toBeEnabled();
  });
  it("routes a real upload sequence through context and revokes old download URLs", async () => {
    const revoke = vi.fn();
    vi.stubGlobal("URL", {
      createObjectURL: vi.fn(() => "blob:fixture"),
      revokeObjectURL: revoke,
    });
    const bytes = new Uint8Array([97]);
    const { sha256 } = await import("./helpers");
    const hash = await sha256(bytes);
    vi.mocked(executionApi.call).mockImplementation(
      async (_context, action) => {
        if (action === "files.list")
          return {
            root_id: "samples",
            path: "",
            entries: [{ name: "a.txt", path: "a.txt", is_dir: false, size: 1 }],
          };
        if (action === "files.stat")
          return { size: 1, sha256: hash, is_dir: false };
        if (action === "files.read")
          return { data_b64: "YQ==", size: 1, offset: 0, eof: true };
        if (action === "files.write_begin") return { upload_id: "upload" };
        if (action === "files.write_chunk") return { bytes_done: 1 };
        return { size: 1, sha256: hash };
      },
    );
    const { container, rerender } = render(
      <RestrictedDeviceFiles
        {...props}
        executionContext={{ ...context, work_mode: "agentic" }}
      />,
    );
    await act(async () => {
      await Promise.resolve();
    });
    const file = new File([bytes], "upload.txt");
    Object.defineProperty(file, "arrayBuffer", {
      value: async () => bytes.buffer,
    });
    fireEvent.change(container.querySelector('input[type="file"]')!, {
      target: { files: [file] },
    });
    await act(async () => {
      await new Promise((yes) => setTimeout(yes, 20));
    });
    expect(
      vi.mocked(executionApi.call).mock.calls.map((args) => args[1]),
    ).toEqual(
      expect.arrayContaining([
        "files.write_begin",
        "files.write_chunk",
        "files.write_commit",
      ]),
    );
    expect(devicesApi.call).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", { name: "devices.downloadNamed" }),
    );
    await act(async () => {
      await new Promise((yes) => setTimeout(yes, 20));
    });
    expect(
      screen.getByRole("link", { name: "devices.saveDownload" }),
    ).toHaveAttribute("href", "blob:fixture");
    rerender(
      <RestrictedDeviceFiles
        {...props}
        executionContext={{ ...context, work_mode: "plan" }}
      />,
    );
    await act(async () => {
      await Promise.resolve();
    });
    expect(revoke).toHaveBeenCalledWith("blob:fixture");
    expect(
      screen.queryByRole("link", { name: "devices.saveDownload" }),
    ).toBeNull();
    vi.unstubAllGlobals();
  });
  it("keeps upload abort within the same execution context", async () => {
    vi.mocked(executionApi.call).mockImplementation(
      async (_context, action) => {
        if (action === "files.list")
          return { root_id: "samples", path: "", entries: [] };
        if (action === "files.write_begin")
          return { upload_id: "failed-upload" };
        if (action === "files.write_chunk")
          throw new Error("upload interrupted");
        return { aborted: true };
      },
    );
    const { container } = render(
      <RestrictedDeviceFiles
        {...props}
        executionContext={{ ...context, work_mode: "agentic" }}
      />,
    );
    await act(async () => {
      await Promise.resolve();
    });
    const file = new File(["a"], "failed.txt");
    Object.defineProperty(file, "arrayBuffer", {
      value: async () => new Uint8Array([97]).buffer,
    });
    fireEvent.change(container.querySelector('input[type="file"]')!, {
      target: { files: [file] },
    });
    await act(async () => {
      await new Promise((yes) => setTimeout(yes, 20));
    });
    expect(executionApi.call).toHaveBeenCalledWith(
      "first",
      "files.write_abort",
      { upload_id: "failed-upload" },
      undefined,
    );
    expect(devicesApi.call).not.toHaveBeenCalled();
  });
  it.each(["begin", "chunk", "chunk-revoked"])(
    "aborts the captured upload after scope switch during %s",
    async (pendingStage) => {
      let complete!: (value: unknown) => void;
      let chunkCount = 0;
      const pending = new Promise((yes) => {
        complete = yes;
      });
      vi.mocked(executionApi.call).mockImplementation(
        async (_context, action) => {
          if (action === "files.list")
            return { entries: [], root_id: "samples", path: "" };
          if (action === "files.write_begin")
            return pendingStage === "begin"
              ? pending
              : { upload_id: "old-upload" };
          if (action === "files.write_chunk") {
            chunkCount++;
            return chunkCount === 1 ? { bytes_done: 1048576 } : pending;
          }
          if (action === "files.write_abort") {
            if (pendingStage === "chunk-revoked")
              throw new Error("permission revoked");
            return { aborted: true };
          }
          throw new Error("unexpected " + action);
        },
      );
      const onError = vi.fn();
      const { container, rerender } = render(
        <RestrictedDeviceFiles
          {...props}
          onError={onError}
          executionContext={{ ...context, work_mode: "agentic" }}
        />,
      );
      await act(async () => {
        await Promise.resolve();
      });
      const bytes = new Uint8Array(1048577);
      const file = new File([bytes], "inflight.bin");
      Object.defineProperty(file, "arrayBuffer", {
        value: async () => bytes.buffer,
      });
      fireEvent.change(container.querySelector('input[type="file"]')!, {
        target: { files: [file] },
      });
      await act(async () => {
        await new Promise((yes) => setTimeout(yes, 50));
      });
      if (pendingStage.startsWith("chunk")) expect(chunkCount).toBe(2);
      rerender(
        <RestrictedDeviceFiles
          {...props}
          onError={onError}
          executionContext={{
            ...context,
            context_id: "second",
            work_mode: "plan",
          }}
        />,
      );
      await act(async () => {
        await Promise.resolve();
        complete(
          pendingStage === "begin"
            ? { upload_id: "old-upload" }
            : { bytes_done: 1048577 },
        );
        await new Promise((yes) => setTimeout(yes, 20));
      });
      expect(executionApi.call).toHaveBeenCalledWith(
        "first",
        "files.write_abort",
        { upload_id: "old-upload" },
        undefined,
      );
      expect(
        vi
          .mocked(executionApi.call)
          .mock.calls.filter((args) => args[0] === "second")
          .every((args) => args[1] === "files.list"),
      ).toBe(true);
      expect(
        screen.getByRole("button", { name: "devices.upload" }),
      ).toBeDisabled();
      expect(screen.queryByText("devices.browserCancelled")).toBeNull();
      expect(onError).not.toHaveBeenCalled();
    },
  );
});
