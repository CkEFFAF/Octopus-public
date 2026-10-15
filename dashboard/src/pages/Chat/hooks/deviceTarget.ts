import { useSyncExternalStore } from "react";
import type { WorkMode } from "../utils/workMode";

/** UI option value only; the wire contract uses a distinct target_kind. */
export const LOCAL_TARGET = "@local";
export function targetOption(
  value?: { device_id?: string | null; target_kind?: string } | null,
): string {
  return value?.target_kind === "local" ? LOCAL_TARGET : value?.device_id ?? "";
}
export function targetFields(option: string): {
  device_id?: string;
  target_kind?: "device" | "local";
} {
  return option === LOCAL_TARGET
    ? { target_kind: "local" }
    : { device_id: option || undefined };
}

export type ExecutionSelection = {
  deviceId: string;
  workingDir?: string;
  workMode: WorkMode;
};
export type ExecutionSelectionSnapshot = ExecutionSelection & { scope: string };
const empty: ExecutionSelection = { deviceId: "", workMode: "agentic" };
const selections = new Map<string, ExecutionSelection>();
export type ExecutionSelectionStatus =
  | "unknown"
  | "loading"
  | "ready"
  | "error";
const selectionStatuses = new Map<string, ExecutionSelectionStatus>();
const listeners = new Set<() => void>();
export function executionScope(
  agentId?: string | null,
  threadId?: string | null,
): string {
  return JSON.stringify([agentId ?? "", threadId ?? ""]);
}
export function getExecutionSelection(scope: string): ExecutionSelection {
  return selections.get(scope) ?? empty;
}
export function getExecutionSelectionStatus(
  scope: string,
): ExecutionSelectionStatus {
  return selectionStatuses.get(scope) ?? "unknown";
}
export function setExecutionSelectionStatus(
  scope: string,
  status: ExecutionSelectionStatus,
): void {
  selectionStatuses.set(scope, status);
  listeners.forEach((listener) => listener());
}
export function executionSelectionReady(
  scope: string,
  threadId?: string | null,
): boolean {
  return (
    !threadId ||
    threadId.startsWith("__") ||
    getExecutionSelectionStatus(scope) === "ready"
  );
}
export function useExecutionSelectionStatus(
  scope: string,
): ExecutionSelectionStatus {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    () => getExecutionSelectionStatus(scope),
    () => "unknown",
  );
}
export function setExecutionSelection(
  scope: string,
  patch: Partial<ExecutionSelection>,
): void {
  selections.set(scope, { ...getExecutionSelection(scope), ...patch });
  listeners.forEach((listener) => listener());
}
export function getSelectedDeviceId(scope: string): string {
  return getExecutionSelection(scope).deviceId;
}
export function setSelectedDeviceId(scope: string, value: string): void {
  setExecutionSelection(scope, { deviceId: value, workingDir: undefined });
}
export function useExecutionSelection(scope: string): ExecutionSelection {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => {
        listeners.delete(listener);
      };
    },
    () => getExecutionSelection(scope),
    () => empty,
  );
}
