import { act, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import {
  executionApi,
  type ExecutionContext,
  type ExecutionTarget,
} from "../../../api/modules/execution";
import ExecutionWorkbench from "./ExecutionWorkbench";
vi.mock("../../../api/modules/execution", () => ({
  executionApi: { target: vi.fn() },
}));
vi.mock("../../Devices/NativeDeviceFiles", () => ({
  default: () => <span>native-files</span>,
}));
vi.mock("../../Devices/DeviceFiles", () => ({
  RestrictedDeviceFiles: () => <span>restricted-files</span>,
}));
vi.mock("../../Devices/DeviceDesktop", () => ({ default: () => null }));
vi.mock("./ChatDockGit", () => ({ default: () => null }));
vi.mock("./ExecutionJobs", () => ({ default: () => null }));
vi.mock("./ExecutionTerminal", () => ({ default: () => null }));
vi.mock("./ExecutionBrowser", () => ({ default: () => null }));
const context: ExecutionContext = {
  context_id: "ctx",
  device_id: "files",
  target_kind: "device",
  working_dir: null,
  work_mode: "ask",
  policy_revision: 1,
  grant_version: 1,
};
describe("workspace filesystem protocol selection", () => {
  it.each(["owner", "restricted", "local", "missing-roots"])(
    "routes %s without changing device trust",
    async (kind) => {
      const target = {
        device_id: kind === "local" ? null : "files",
        target_kind: kind === "local" ? "local" : "device",
        name: "Files",
        trust_mode: kind === "owner" ? "owner" : "restricted",
        ...(kind !== "missing-roots" ? { roots: [] } : {}),
      } as ExecutionTarget;
      vi.mocked(executionApi.target).mockResolvedValueOnce(target);
      render(
        <ExecutionWorkbench
          context={{
            ...context,
            target_kind: kind === "local" ? "local" : "device",
          }}
          surface="workspace"
          visible
        />,
      );
      await act(async () => {
        await Promise.resolve();
      });
      if (kind === "missing-roots")
        expect(screen.getByRole("alert")).toBeInTheDocument();
      else
        expect(
          screen.getByText(
            kind === "restricted" ? "restricted-files" : "native-files",
          ),
        ).toBeInTheDocument();
      expect(target.trust_mode).toBe(kind === "owner" ? "owner" : "restricted");
    },
  );
});
