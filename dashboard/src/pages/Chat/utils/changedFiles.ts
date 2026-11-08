import { canonicalizeDockFilePath, type DockFileRef } from "./dockFilePath";
import type { TurnFileChange } from "./turnFileChanges";

export function changedFileKey(
  path: string,
  agentId?: string,
  deviceId?: string,
) {
  return JSON.stringify([
    agentId ?? "",
    deviceId ?? "",
    canonicalizeDockFilePath(path, agentId),
  ]);
}

/** Preserve producer/device identity. A turn's recorded diff never comes from disk. */
export function mergeChangedFiles(
  paths: DockFileRef[],
  history: TurnFileChange[],
  current: TurnFileChange[],
  agentId: string,
) {
  const result = new Map<string, TurnFileChange>();
  for (const ref of paths) {
    const owner = ref.agentId || agentId;
    const key = changedFileKey(ref.path, owner);
    result.set(key, {
      key,
      path: ref.path,
      agentId: owner,
      confirmed: false,
      edits: [],
    });
  }
  for (const file of [...history, ...current]) {
    const key = changedFileKey(
      file.path,
      file.agentId || agentId,
      file.deviceId,
    );
    result.set(key, { ...file, agentId: file.agentId || agentId, key });
  }
  return [...result.values()];
}
