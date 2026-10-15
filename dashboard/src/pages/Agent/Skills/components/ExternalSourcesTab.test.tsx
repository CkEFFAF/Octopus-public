import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { devicesApi, type Device } from "../../../../api/modules/devices";
import { executionApi } from "../../../../api/modules/execution";
import {
  externalSourcesApi,
  type ExternalSkill,
} from "../../../../api/modules/externalSources";
import ExternalSourcesTab from "./ExternalSourcesTab";

vi.mock("../../../../api/modules/devices", () => ({
  devicesApi: { list: vi.fn() },
}));
vi.mock("../../../../api/modules/execution", () => ({
  executionApi: { createContext: vi.fn() },
}));
vi.mock("../../../../api/modules/externalSources", () => ({
  externalSourcesApi: { discover: vi.fn(), inspect: vi.fn(), import: vi.fn() },
}));
vi.mock("../../../../utils/showApiToast", () => ({ showApiError: vi.fn() }));
vi.mock("antd", async (original) => ({
  ...(await original<typeof import("antd")>()),
  Select: ({
    options,
    onChange,
    value,
    ...props
  }: {
    options: { value: string; label: string; disabled?: boolean }[];
    value: string;
    onChange: (value: string) => void;
    "aria-label": string;
  }) => (
    <select
      aria-label={props["aria-label"]}
      value={value ?? ""}
      onChange={(event) => onChange(event.target.value)}
    >
      <option value="" />
      {options.map((option) => (
        <option
          key={option.value}
          value={option.value}
          disabled={option.disabled}
        >
          {option.label}
        </option>
      ))}
    </select>
  ),
}));

const candidate: ExternalSkill = {
  source: "codex",
  slug: "review",
  name: "Device review",
  description: "Check code",
  digest: "original-digest",
  manifest: "",
  files: [],
  file_count: 1,
  needs_inspection: true,
  execution_context_id: "context-A",
  device_id: "A",
};
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(devicesApi.list).mockResolvedValue({
    devices: ["A", "B"].map(
      (id) =>
        ({
          device_id: id,
          name: id,
          online: true,
          revoked_at: null,
          trust_mode: "owner",
          runtime: { capability_protocol_version: 1 },
        }) as Device,
    ),
  });
  vi.mocked(executionApi.createContext).mockImplementation(async (values) => ({
    context_id: `context-${values.device_id}`,
    device_id: values.device_id!,
    working_dir: "/work",
    work_mode: "ask",
    policy_revision: 1,
    grant_version: 1,
  }));
});

it("requires an explicit source and imports the inspected frozen device snapshot", async () => {
  vi.mocked(externalSourcesApi.discover).mockResolvedValue([candidate]);
  let inspected!: (value: Partial<ExternalSkill>) => void;
  vi.mocked(externalSourcesApi.inspect).mockReturnValue(
    new Promise((resolve) => {
      inspected = resolve;
    }),
  );
  vi.mocked(externalSourcesApi.import).mockResolvedValue({});
  render(
    <ExternalSourcesTab
      agentId="expert"
      installed={[]}
      onImported={vi.fn().mockResolvedValue(undefined)}
    />,
  );
  const picker = await screen.findByRole("combobox");
  await waitFor(() =>
    expect(screen.getByRole("option", { name: /A ·/ })).toBeInTheDocument(),
  );
  expect(externalSourcesApi.discover).not.toHaveBeenCalled();
  fireEvent.change(picker, { target: { value: "A" } });
  fireEvent.click(await screen.findByText("Device review"));
  expect(
    screen.getByRole("button", { name: "skills.external.approve" }),
  ).toBeDisabled();
  await act(async () =>
    inspected({ manifest: "# Exact reviewed content", files: ["SKILL.md"] }),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "skills.external.approve" }),
  );
  await waitFor(() =>
    expect(externalSourcesApi.import).toHaveBeenCalledWith(
      "expert",
      expect.objectContaining({
        execution_context_id: "context-A",
        digest: "original-digest",
        needs_inspection: false,
      }),
    ),
  );
  expect(executionApi.createContext).toHaveBeenCalledWith({
    agent_id: "expert",
    device_id: "A",
    work_mode: "ask",
  });
});

it("discards a late response from the previous source", async () => {
  let previous!: (value: ExternalSkill[]) => void;
  vi.mocked(externalSourcesApi.discover).mockImplementation(
    (_agent, context) =>
      context === "context-A"
        ? new Promise((resolve) => {
            previous = resolve;
          })
        : Promise.resolve([
            {
              ...candidate,
              name: "From B",
              execution_context_id: "context-B",
              device_id: "B",
            },
          ]),
  );
  render(
    <ExternalSourcesTab agentId="expert" installed={[]} onImported={vi.fn()} />,
  );
  const picker = await screen.findByRole("combobox");
  await waitFor(() =>
    expect(screen.getByRole("option", { name: /A ·/ })).toBeInTheDocument(),
  );
  fireEvent.change(picker, { target: { value: "A" } });
  await waitFor(() =>
    expect(externalSourcesApi.discover).toHaveBeenCalledWith(
      "expert",
      "context-A",
      expect.anything(),
    ),
  );
  fireEvent.change(picker, { target: { value: "B" } });
  expect(await screen.findByText("From B")).toBeInTheDocument();
  await act(async () => previous([candidate]));
  expect(screen.queryByText("Device review")).not.toBeInTheDocument();
  expect(screen.getByText("From B")).toBeInTheDocument();
});
