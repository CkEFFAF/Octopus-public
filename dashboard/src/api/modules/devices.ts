import { request } from "../request";

export type DevicePermission =
  | "desktop_view"
  | "desktop_control"
  | "files_read"
  | "files_write"
  | "command_exec"
  | "acp_run";

export interface DeviceRoot {
  id: string;
  name: string;
  path: string;
  read: boolean;
  write: boolean;
}

export interface Device {
  device_id: string;
  name: string;
  platform: string;
  capabilities: string[];
  permissions: string[];
  roots: DeviceRoot[];
  grant_version: number;
  remote_grant_mode?: "confirm" | "owner_auto";
  pending_proposal?: {
    proposal_id: string;
    permissions: string[];
    roots: DeviceRoot[];
    requires_confirm: boolean;
    expires_at: number;
  } | null;
  online: boolean;
  last_seen_at: number | null;
  revoked_at: number | null;
}


export type DesktopTakeoverMode = "view" | "view_control";
export type DesktopTakeoverStatus =
  | "pending"
  | "accepted"
  | "rejected"
  | "timeout"
  | "cancelled";

export interface DesktopTargetState {
  device_id: string | null;
  device: Device | null;
  pending_takeover: {
    request_id: string;
    to_device_id: string;
    from_device_id: string | null;
    mode: DesktopTakeoverMode;
    status: DesktopTakeoverStatus;
    expires_at: number;
  } | null;
  note?: string;
}

export interface DesktopTakeoverRequest {
  request_id: string | null;
  from_device_id: string | null;
  to_device_id: string;
  mode: DesktopTakeoverMode;
  status: DesktopTakeoverStatus;
  expires_at?: number;
  current_device_id: string | null;
}

export type DeviceOperationStatus =
  | "pending_confirmation"
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelled"
  | "unknown";

export interface DeviceOperation {
  operation_id: string;
  device_id: string;
  owner_user_id: number;
  agent_id: string | null;
  action: string;
  params: Record<string, unknown>;
  status: DeviceOperationStatus;
  result: Record<string, unknown> | null;
  error: string | null;
  created_at: number;
  updated_at: number;
}

export interface DeviceFileEntry {
  name: string;
  path: string;
  is_dir: boolean;
  size: number;
}

export interface DeviceInput {
  kind: "click" | "move" | "scroll" | "type" | "key";
  x?: number;
  y?: number;
  button?: "left" | "right";
  text?: string;
  key?: string;
  dy?: number;
}

interface DeviceCalls {
  "files.list": {
    params: { root_id: string; path: string };
    result: { entries: DeviceFileEntry[]; root_id: string; path: string };
  };
  "files.stat": {
    params: { root_id: string; path: string };
    result: { size: number; sha256: string; is_dir: boolean };
  };
  "files.read": {
    params: { root_id: string; path: string; offset: number; length: number };
    result: { data_b64: string; size: number; offset: number; eof: boolean };
  };
  "files.write_begin": {
    params: { root_id: string; path: string; size: number; sha256: string };
    result: { upload_id: string };
  };
  "files.write_chunk": {
    params: { upload_id: string; offset: number; data_b64: string };
    result: { bytes_done: number };
  };
  "files.write_commit": {
    params: { upload_id: string };
    result: { size: number; sha256: string; path: string };
  };
  "files.write_abort": {
    params: { upload_id: string };
    result: { aborted: boolean };
  };
  "desktop.capture": {
    params: { quality?: number };
    result: { jpeg_b64: string; width: number; height: number };
  };
  "desktop.input": { params: DeviceInput; result: { ok: boolean } };
}

const devicePath = (id: string) => `/devices/${encodeURIComponent(id)}`;
const operationPath = (id: string) =>
  `/devices/operations/${encodeURIComponent(id)}`;
const post = <T>(path: string, body: unknown, signal?: AbortSignal) =>
  request<T>(path, { method: "POST", body: JSON.stringify(body), signal });

async function boundedCall<T>(
  path: string,
  body: unknown,
  signal?: AbortSignal,
) {
  const controller = new AbortController();
  const abort = () => controller.abort();
  if (signal?.aborted) abort();
  signal?.addEventListener("abort", abort, { once: true });
  const timer = setTimeout(abort, 20000);
  try {
    return await post<T>(path, body, controller.signal);
  } finally {
    clearTimeout(timer);
    signal?.removeEventListener("abort", abort);
  }
}

export const devicesApi = {
  desktopTarget: () =>
    request<DesktopTargetState>("/devices/desktop-target"),
  switchDesktopTarget: (device_id: string, mode: DesktopTakeoverMode = "view") =>
    post<DesktopTakeoverRequest>("/devices/desktop-target/switch", {
      device_id,
      mode,
    }),
  desktopTakeoverRequest: (requestId: string) =>
    request<DesktopTakeoverRequest>(
      `/devices/desktop-target/requests/${encodeURIComponent(requestId)}`,
    ),
  desktopTakeoverEvents: () =>
    request<{ events: Array<Record<string, unknown>> }>(
      "/devices/desktop-target/events",
    ),
  list: () => request<{ devices: Device[] }>("/devices"),
  pairing: () =>
    post<{ pairing_code: string; expires_at: number }>("/devices/pairing", {}),
  update: (id: string, changes: { name?: string; permissions?: string[] }) =>
    request<Device>(devicePath(id), {
      method: "PATCH",
      body: JSON.stringify(changes),
    }),
  revoke: (id: string) => post<Device>(`${devicePath(id)}/revoke`, {}),
  operations: (deviceId?: string, signal?: AbortSignal) =>
    request<{ operations: DeviceOperation[] }>(
      `/devices/operations${
        deviceId ? `?device_id=${encodeURIComponent(deviceId)}` : ""
      }`,
      { signal },
    ),
  operation: (id: string) => request<DeviceOperation>(operationPath(id)),
  submit: (id: string, action: string, params: Record<string, unknown>) =>
    post<DeviceOperation>(`${devicePath(id)}/operations`, { action, params }),
  cancel: (id: string) =>
    post<DeviceOperation>(`${operationPath(id)}/cancel`, {}),
  confirm: (id: string) =>
    post<DeviceOperation>(`${operationPath(id)}/confirm`, {}),
  transfer: (params: {
    source_device_id: string;
    source_root_id: string;
    source_path: string;
    target_device_id: string;
    target_root_id: string;
    target_path: string;
  }) => post<DeviceOperation>("/devices/transfers", params),
  call: <K extends keyof DeviceCalls>(
    id: string,
    action: K,
    params: DeviceCalls[K]["params"],
    signal?: AbortSignal,
  ) =>
    boundedCall<DeviceCalls[K]["result"]>(
      `${devicePath(id)}/call`,
      { action, params },
      signal,
    ),
};
