import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  devicesApi,
  type Device,
  type DeviceExecutionSelection,
} from "../../../api/modules/devices";
import DeviceTargetSelect from "./DeviceTargetSelect";
import { executionApi } from "../../../api/modules/execution";
import {
  executionScope,
  setExecutionSelection,
  getExecutionSelection,
  getExecutionSelectionStatus,
} from "../hooks/deviceTarget";

vi.mock("../../../api/modules/devices", () => ({
  devicesApi: {
    list: vi.fn(),
    executionSelection: vi.fn(),
    saveExecutionSelection: vi.fn(),
  },
}));
vi.mock("../../../api/modules/execution", () => ({
  executionApi: {
    defaultTarget: vi.fn(),
    saveDefaultTarget: vi.fn(),
    localAvailable: vi.fn(),
  },
}));

const device = (id: string, name = id): Device =>
  ({
    device_id: id,
    name,
    online: true,
    revoked_at: null,
    trust_mode: "owner",
    capabilities: [],
    permissions: [],
    roots: [],
    working_dir: "/home/operator",
    policy_revision: 1,
    applied_policy_revision: 1,
  }) as Device;
const stored = (
  deviceId: string | null,
  workingDir: string | null = null,
): DeviceExecutionSelection => ({
  device_id: deviceId,
  working_dir: workingDir,
  work_mode: "agentic",
  target_kind: "device",
});
const deferred = <T,>() => {
  let resolve!: (value: T) => void;
  let reject!: (reason: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
};
const openTargets = () =>
  fireEvent.click(screen.getByRole("button", { name: "devices.targetDevice" }));
const chooseTarget = async (name: string) => {
  fireEvent.mouseDown(screen.getByRole("combobox"));
  fireEvent.click(
    await screen.findByText(`${name} · devices.online`, {
      selector: ".ant-select-item-option-content",
    }),
  );
};

describe("DeviceTargetSelect", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.mocked(devicesApi.list).mockResolvedValue({
      devices: [device("office"), device("gpu"), device("laptop")],
    });
    vi.mocked(devicesApi.executionSelection).mockResolvedValue(stored(null));
    vi.mocked(devicesApi.saveExecutionSelection).mockImplementation(
      async (_thread, selection) => ({ ...stored(null), ...selection }),
    );
    vi.mocked(executionApi.localAvailable).mockResolvedValue({
      available: false,
    });
    vi.mocked(executionApi.defaultTarget).mockResolvedValue({
      device_id: null,
      working_dir: null,
    });
  });

  it("keeps an explicit selection entry when no device is configured", async () => {
    vi.mocked(devicesApi.list).mockResolvedValue({ devices: [] });
    render(<DeviceTargetSelect />);

    await waitFor(() => expect(devicesApi.list).toHaveBeenCalled());
    expect(
      screen.getByRole("button", { name: "devices.targetDevice" }),
    ).toHaveTextContent("devices.noTarget");
  });

  it("retains an unavailable selected device instead of silently using a default", async () => {
    const scope = executionScope("missing-target-agent");
    setExecutionSelection(scope, { deviceId: "removed-device" });
    vi.mocked(devicesApi.list).mockResolvedValue({ devices: [] });
    vi.mocked(executionApi.defaultTarget).mockResolvedValue({
      device_id: "different-device",
      working_dir: null,
    });
    render(<DeviceTargetSelect agentId="missing-target-agent" />);
    await waitFor(() => expect(devicesApi.list).toHaveBeenCalled());
    expect(
      screen.getByRole("button", { name: "devices.targetDevice" }),
    ).toHaveTextContent("devices.targetUnavailable");
    expect(getExecutionSelection(scope).deviceId).toBe("removed-device");
  });

  it("restores a local account target explicitly without selecting a remote device", async () => {
    vi.mocked(devicesApi.list).mockResolvedValue({ devices: [] });
    vi.mocked(executionApi.localAvailable).mockResolvedValue({
      available: true,
    });
    vi.mocked(executionApi.defaultTarget).mockResolvedValue({
      target_kind: "local",
      device_id: null,
      working_dir: "/home/operator",
    });
    render(<DeviceTargetSelect agentId="local-default-expert" />);
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "devices.targetDevice" }),
      ).toHaveTextContent("devices.localExecution"),
    );
    fireEvent.click(
      screen.getByRole("button", { name: "devices.targetDevice" }),
    );
    await waitFor(() =>
      expect(screen.getByText("devices.localExecutionHint")).toBeVisible(),
    );
  });

  it("shows an available device and the management entry", async () => {
    vi.mocked(devicesApi.list).mockResolvedValue({
      devices: [
        {
          device_id: "device-1",
          name: "Office PC",
          online: true,
          revoked_at: null,
        } as Device,
      ],
    });
    render(<DeviceTargetSelect />);

    fireEvent.click(
      await screen.findByRole("button", { name: "devices.targetDevice" }),
    );
    expect(await screen.findByRole("combobox")).toBeInTheDocument();
    expect(screen.getByRole("link")).toHaveAttribute("href", "/devices");
  });

  it("persists target changes and restores them after refreshing the session", async () => {
    const scope = executionScope("persist-agent", "persist-thread");
    let saved = stored(null);
    vi.mocked(devicesApi.executionSelection).mockImplementation(
      async () => saved,
    );
    vi.mocked(devicesApi.saveExecutionSelection).mockImplementation(
      async (_thread, selection) => (saved = { ...saved, ...selection }),
    );
    const first = render(
      <DeviceTargetSelect agentId="persist-agent" threadId="persist-thread" />,
    );
    await waitFor(() =>
      expect(devicesApi.executionSelection).toHaveBeenCalled(),
    );
    openTargets();
    await chooseTarget("gpu");
    await waitFor(() =>
      expect(getExecutionSelection(scope).deviceId).toBe("gpu"),
    );
    expect(devicesApi.saveExecutionSelection).toHaveBeenLastCalledWith(
      "persist-thread",
      { target_kind: "device", device_id: "gpu", working_dir: null },
    );
    first.unmount();
    expect(getExecutionSelectionStatus(scope)).toBe("unknown");
    setExecutionSelection(scope, { deviceId: "", workingDir: undefined });
    render(
      <DeviceTargetSelect agentId="persist-agent" threadId="persist-thread" />,
    );
    await waitFor(() =>
      expect(getExecutionSelection(scope).deviceId).toBe("gpu"),
    );
    expect(
      screen.getByRole("button", { name: "devices.targetDevice" }),
    ).toHaveTextContent("gpu");
    expect(executionApi.saveDefaultTarget).not.toHaveBeenCalled();
  });

  it("applies a session directory and clears it when selecting another device", async () => {
    const scope = executionScope("directory-agent", "directory-thread");
    vi.mocked(devicesApi.executionSelection).mockResolvedValue(
      stored("office"),
    );
    render(
      <DeviceTargetSelect
        agentId="directory-agent"
        threadId="directory-thread"
      />,
    );
    await waitFor(() =>
      expect(getExecutionSelection(scope).deviceId).toBe("office"),
    );
    openTargets();
    fireEvent.change(
      await screen.findByRole("textbox", { name: "devices.sessionWorkingDir" }),
      {
        target: { value: "/srv/project outside home" },
      },
    );
    expect(getExecutionSelection(scope).workingDir).toBeUndefined();
    fireEvent.click(
      screen.getByRole("button", { name: "devices.applySessionDirectory" }),
    );
    await waitFor(() =>
      expect(getExecutionSelection(scope).workingDir).toBe(
        "/srv/project outside home",
      ),
    );
    expect(devicesApi.saveExecutionSelection).toHaveBeenLastCalledWith(
      "directory-thread",
      {
        target_kind: "device",
        device_id: "office",
        working_dir: "/srv/project outside home",
      },
    );
    await chooseTarget("gpu");
    await waitFor(() =>
      expect(getExecutionSelection(scope).deviceId).toBe("gpu"),
    );
    expect(getExecutionSelection(scope).workingDir).toBeUndefined();
    expect(devicesApi.saveExecutionSelection).toHaveBeenLastCalledWith(
      "directory-thread",
      { target_kind: "device", device_id: "gpu", working_dir: null },
    );
    expect(executionApi.saveDefaultTarget).not.toHaveBeenCalled();
  });

  it("keeps new-thread target and directory changes in memory until the thread exists", async () => {
    const scope = executionScope("draft-agent", "__new__");
    render(<DeviceTargetSelect agentId="draft-agent" threadId="__new__" />);
    openTargets();
    await chooseTarget("office");
    fireEvent.change(
      await screen.findByRole("textbox", { name: "devices.sessionWorkingDir" }),
      {
        target: { value: "D:\\projects\\experiment" },
      },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "devices.applySessionDirectory" }),
    );
    expect(getExecutionSelection(scope)).toMatchObject({
      deviceId: "office",
      workingDir: "D:\\projects\\experiment",
    });
    expect(devicesApi.executionSelection).not.toHaveBeenCalled();
    expect(devicesApi.saveExecutionSelection).not.toHaveBeenCalled();
  });

  it("clears an explicit directory to inherit the target default", async () => {
    const scope = executionScope("clear-dir-agent", "clear-dir-thread");
    vi.mocked(devicesApi.executionSelection).mockResolvedValue(
      stored("office", "/saved/project"),
    );
    render(
      <DeviceTargetSelect
        agentId="clear-dir-agent"
        threadId="clear-dir-thread"
      />,
    );
    await waitFor(() =>
      expect(getExecutionSelection(scope).workingDir).toBe("/saved/project"),
    );
    openTargets();
    fireEvent.change(
      await screen.findByRole("textbox", { name: "devices.sessionWorkingDir" }),
      { target: { value: "" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "devices.applySessionDirectory" }),
    );
    await waitFor(() =>
      expect(getExecutionSelection(scope).workingDir).toBeUndefined(),
    );
    expect(devicesApi.saveExecutionSelection).toHaveBeenLastCalledWith(
      "clear-dir-thread",
      { target_kind: "device", device_id: "office", working_dir: null },
    );
  });

  it("prevents directory edits before hydration and restores the saved target directory", async () => {
    const scope = executionScope("restore-race-agent", "restore-race-thread");
    const restoring = deferred<DeviceExecutionSelection>();
    vi.mocked(devicesApi.executionSelection).mockReturnValue(restoring.promise);
    render(
      <DeviceTargetSelect
        agentId="restore-race-agent"
        threadId="restore-race-thread"
        defaultDeviceId="office"
      />,
    );
    openTargets();
    expect(screen.getByRole("combobox")).toBeDisabled();
    expect(
      screen.queryByRole("textbox", { name: "devices.sessionWorkingDir" }),
    ).not.toBeInTheDocument();
    expect(devicesApi.saveExecutionSelection).not.toHaveBeenCalled();
    await act(async () => restoring.resolve(stored("gpu", "/saved/project")));
    expect(getExecutionSelection(scope).workingDir).toBe("/saved/project");
    expect(
      screen.getByRole("textbox", { name: "devices.sessionWorkingDir" }),
    ).toHaveValue("/saved/project");
    fireEvent.change(
      screen.getByRole("textbox", { name: "devices.sessionWorkingDir" }),
      { target: { value: "/draft/project" } },
    );
    act(() => setExecutionSelection(scope, { workMode: "debug" }));
    expect(
      screen.getByRole("textbox", { name: "devices.sessionWorkingDir" }),
    ).toHaveValue("/draft/project");
  });

  it("hydrates device and directory while preserving a mode changed during loading", async () => {
    const scope = executionScope("mode-restore-agent", "mode-restore-thread");
    const restoring = deferred<DeviceExecutionSelection>();
    vi.mocked(devicesApi.executionSelection).mockReturnValue(restoring.promise);
    render(
      <DeviceTargetSelect
        agentId="mode-restore-agent"
        threadId="mode-restore-thread"
      />,
    );
    act(() => setExecutionSelection(scope, { workMode: "plan" }));
    await act(async () =>
      restoring.resolve({
        ...stored("gpu", "/srv/experiment"),
        work_mode: "debug",
      }),
    );
    expect(getExecutionSelection(scope)).toEqual({
      deviceId: "gpu",
      workingDir: "/srv/experiment",
      workMode: "plan",
    });
    expect(getExecutionSelectionStatus(scope)).toBe("ready");
  });

  it.each(["expert", "account"] as const)(
    "does not present the %s default as the session target after hydration fails",
    async (fallback) => {
      const scope = executionScope(
        `restore-failed-${fallback}`,
        "stored-thread",
      );
      vi.mocked(devicesApi.executionSelection).mockRejectedValue(
        new Error("selection unavailable"),
      );
      vi.mocked(executionApi.defaultTarget).mockResolvedValue(stored("laptop"));
      render(
        <DeviceTargetSelect
          agentId={`restore-failed-${fallback}`}
          threadId="stored-thread"
          defaultDeviceId={fallback === "expert" ? "office" : undefined}
        />,
      );
      await waitFor(() =>
        expect(getExecutionSelectionStatus(scope)).toBe("error"),
      );
      expect(
        screen.getByRole("button", { name: "devices.targetDevice" }),
      ).toHaveTextContent("devices.sessionSelectionFailed");
      openTargets();
      expect(screen.getByRole("combobox")).toBeDisabled();
      expect(getExecutionSelectionStatus(scope)).toBe("error");
      expect(devicesApi.saveExecutionSelection).not.toHaveBeenCalled();
      act(() => setExecutionSelection(scope, { workMode: "plan" }));
      vi.mocked(devicesApi.executionSelection).mockResolvedValue(
        stored("gpu", "/restored"),
      );
      fireEvent.click(
        screen.getByRole("button", { name: "devices.retrySessionSelection" }),
      );
      await waitFor(() =>
        expect(getExecutionSelectionStatus(scope)).toBe("ready"),
      );
      expect(getExecutionSelection(scope)).toMatchObject({
        deviceId: "gpu",
        workingDir: "/restored",
        workMode: "plan",
      });
    },
  );

  it("clears the persisted explicit target via PUT before later chat inheritance", async () => {
    const scope = executionScope("clear-target-agent", "clear-target-thread");
    vi.mocked(devicesApi.executionSelection).mockResolvedValue(
      stored("gpu", "/srv/project"),
    );
    render(
      <DeviceTargetSelect
        agentId="clear-target-agent"
        threadId="clear-target-thread"
        defaultDeviceId="office"
      />,
    );
    await waitFor(() =>
      expect(getExecutionSelectionStatus(scope)).toBe("ready"),
    );
    openTargets();
    fireEvent.mouseDown(document.querySelector(".ant-select-clear")!);
    await waitFor(() => expect(getExecutionSelection(scope).deviceId).toBe(""));
    expect(devicesApi.saveExecutionSelection).toHaveBeenLastCalledWith(
      "clear-target-thread",
      { target_kind: "device", device_id: null, working_dir: null },
    );
    expect(getExecutionSelection(scope).workingDir).toBeUndefined();
  });

  it("provides session directories for explicit local targets and sends their typed target", async () => {
    const scope = executionScope("local-session-agent", "local-session-thread");
    vi.mocked(executionApi.localAvailable).mockResolvedValue({
      available: true,
    });
    vi.mocked(devicesApi.executionSelection).mockResolvedValue({
      ...stored(null),
      target_kind: "local",
    });
    render(
      <DeviceTargetSelect
        agentId="local-session-agent"
        threadId="local-session-thread"
      />,
    );
    await waitFor(() =>
      expect(getExecutionSelection(scope).deviceId).toBe("@local"),
    );
    openTargets();
    fireEvent.change(
      await screen.findByRole("textbox", { name: "devices.sessionWorkingDir" }),
      {
        target: { value: "/srv/controller-project" },
      },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "devices.applySessionDirectory" }),
    );
    await waitFor(() =>
      expect(getExecutionSelection(scope).workingDir).toBe(
        "/srv/controller-project",
      ),
    );
    expect(devicesApi.saveExecutionSelection).toHaveBeenLastCalledWith(
      "local-session-thread",
      {
        target_kind: "local",
        device_id: null,
        working_dir: "/srv/controller-project",
      },
    );
  });

  it("does not expose native session directory controls for restricted devices", async () => {
    vi.mocked(devicesApi.list).mockResolvedValue({
      devices: [{ ...device("restricted"), trust_mode: "restricted" }],
    });
    vi.mocked(devicesApi.executionSelection).mockResolvedValue(
      stored("restricted"),
    );
    render(
      <DeviceTargetSelect
        agentId="restricted-agent"
        threadId="restricted-thread"
      />,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: "devices.targetDevice" }),
      ).toHaveTextContent("restricted"),
    );
    openTargets();
    expect(
      screen.queryByRole("textbox", { name: "devices.sessionWorkingDir" }),
    ).not.toBeInTheDocument();
  });

  it("keeps the previous target active and shows a visible error when saving fails", async () => {
    const scope = executionScope("failed-agent", "failed-thread");
    vi.mocked(devicesApi.executionSelection).mockResolvedValue(
      stored("office", "/original"),
    );
    vi.mocked(devicesApi.saveExecutionSelection).mockRejectedValue(
      new Error("offline"),
    );
    render(
      <DeviceTargetSelect agentId="failed-agent" threadId="failed-thread" />,
    );
    await waitFor(() =>
      expect(getExecutionSelection(scope).deviceId).toBe("office"),
    );
    openTargets();
    await chooseTarget("gpu");
    await waitFor(() =>
      expect(screen.getByText("devices.sessionSaveFailed")).toBeVisible(),
    );
    expect(getExecutionSelection(scope)).toMatchObject({
      deviceId: "office",
      workingDir: "/original",
    });
    expect(
      screen.getByRole("button", { name: "devices.targetDevice" }),
    ).toHaveTextContent("office");
    expect(
      screen.getByRole("textbox", { name: "devices.sessionWorkingDir" }),
    ).toHaveValue("/original");
  });

  it("retains a failed directory draft for retry without presenting it as active", async () => {
    const scope = executionScope("failed-dir-agent", "failed-dir-thread");
    vi.mocked(devicesApi.executionSelection).mockResolvedValue(
      stored("office", "/original"),
    );
    vi.mocked(devicesApi.saveExecutionSelection).mockRejectedValue(
      new Error("offline"),
    );
    render(
      <DeviceTargetSelect
        agentId="failed-dir-agent"
        threadId="failed-dir-thread"
      />,
    );
    await waitFor(() =>
      expect(getExecutionSelection(scope).workingDir).toBe("/original"),
    );
    openTargets();
    fireEvent.change(
      await screen.findByRole("textbox", { name: "devices.sessionWorkingDir" }),
      { target: { value: "/new-project" } },
    );
    fireEvent.click(
      screen.getByRole("button", { name: "devices.applySessionDirectory" }),
    );
    await waitFor(() =>
      expect(screen.getByText("devices.sessionSaveFailed")).toBeVisible(),
    );
    expect(getExecutionSelection(scope).workingDir).toBe("/original");
    expect(
      screen.getByRole("textbox", { name: "devices.sessionWorkingDir" }),
    ).toHaveValue("/new-project");
  });

  it("serializes device changes and ignores an older device response", async () => {
    const scope = executionScope("race-agent", "race-thread");
    const first = deferred<DeviceExecutionSelection>();
    const second = deferred<DeviceExecutionSelection>();
    vi.mocked(devicesApi.executionSelection).mockResolvedValue(
      stored("office", "/original"),
    );
    vi.mocked(devicesApi.saveExecutionSelection)
      .mockReturnValueOnce(first.promise)
      .mockReturnValueOnce(second.promise);
    render(<DeviceTargetSelect agentId="race-agent" threadId="race-thread" />);
    await waitFor(() =>
      expect(getExecutionSelection(scope).deviceId).toBe("office"),
    );
    openTargets();
    await chooseTarget("gpu");
    await waitFor(() =>
      expect(devicesApi.saveExecutionSelection).toHaveBeenCalledTimes(1),
    );
    await chooseTarget("laptop");
    expect(devicesApi.saveExecutionSelection).toHaveBeenCalledTimes(1);
    await act(async () => first.resolve(stored("gpu")));
    await waitFor(() =>
      expect(devicesApi.saveExecutionSelection).toHaveBeenCalledTimes(2),
    );
    expect(getExecutionSelection(scope).deviceId).toBe("office");
    await act(async () => second.resolve(stored("laptop")));
    await waitFor(() =>
      expect(getExecutionSelection(scope).deviceId).toBe("laptop"),
    );
    expect(getExecutionSelection(scope).workingDir).toBeUndefined();
  });

  it.each(["resolve", "reject"] as const)(
    "ignores a late save %s after switching threads",
    async (outcome) => {
      const oldScope = executionScope(`scope-${outcome}`, "first-thread");
      const newScope = executionScope(`scope-${outcome}`, "second-thread");
      const pending = deferred<DeviceExecutionSelection>();
      vi.mocked(devicesApi.executionSelection).mockImplementation(
        async (thread) =>
          stored(thread === "first-thread" ? "office" : "laptop", "/original"),
      );
      vi.mocked(devicesApi.saveExecutionSelection).mockReturnValue(
        pending.promise,
      );
      const { rerender } = render(
        <DeviceTargetSelect
          agentId={`scope-${outcome}`}
          threadId="first-thread"
        />,
      );
      await waitFor(() =>
        expect(getExecutionSelection(oldScope).deviceId).toBe("office"),
      );
      openTargets();
      await chooseTarget("gpu");
      await waitFor(() =>
        expect(devicesApi.saveExecutionSelection).toHaveBeenCalledTimes(1),
      );
      rerender(
        <DeviceTargetSelect
          agentId={`scope-${outcome}`}
          threadId="second-thread"
        />,
      );
      await waitFor(() =>
        expect(getExecutionSelection(newScope).deviceId).toBe("laptop"),
      );
      await act(async () => {
        if (outcome === "resolve") pending.resolve(stored("gpu"));
        else pending.reject(new Error("late failure"));
      });
      expect(getExecutionSelection(newScope)).toMatchObject({
        deviceId: "laptop",
        workingDir: "/original",
      });
      openTargets();
      expect(
        screen.queryByText("devices.sessionSaveFailed"),
      ).not.toBeInTheDocument();
      expect(
        screen.getByRole("textbox", { name: "devices.sessionWorkingDir" }),
      ).toHaveValue("/original");
    },
  );
});
