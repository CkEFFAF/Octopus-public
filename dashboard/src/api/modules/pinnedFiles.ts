import { request } from "../request";

export interface PinnedFile {
  id: string;
  title: string;
  scope: "expert" | "project";
  path: string;
  target_kind?: "device" | "local" | null;
  device_id?: string | null;
  working_dir?: string | null;
}
export interface PinnedFiles {
  revision: number;
  files: PinnedFile[];
}
const base = (agent: string) =>
  `/agents/${encodeURIComponent(agent)}/pinned-files`;
export const pinnedFilesApi = {
  get: (agent: string) => request<PinnedFiles>(base(agent)),
  save: (agent: string, value: PinnedFiles) =>
    request<PinnedFiles>(base(agent), {
      method: "PUT",
      body: JSON.stringify(value),
    }),
};
