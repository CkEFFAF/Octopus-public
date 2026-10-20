import { request } from "../request";
import { fileScope } from "./fileSources";

export interface FileAnchor {
  kind:
    | "file"
    | "text"
    | "image"
    | "page"
    | "slide"
    | "document"
    | "sheet"
    | "time";
  quote?: string;
  line?: number;
  column?: number;
  end_line?: number;
  end_column?: number;
  page?: number;
  rect?: [number, number, number, number];
  sheet?: string;
  cells?: string;
  start?: number;
  end?: number;
}
export interface FileAnnotation {
  annotation_id: string;
  resource_id: string;
  version: string;
  anchor: FileAnchor;
  body: string;
  status: "open" | "resolved";
  revision: number;
  cursor: number;
  replies: { body: string; author: number; created_at: number }[];
}
export interface ModificationRequest {
  request_id: string;
  state: string;
  source_version: string;
  text: string;
  results: { resource_id: string; version: string }[];
  receipt?: { status: string; event_id: string };
}
const resourceBase = (a: string, t: string, r: string) =>
  `${fileScope(a, t)}/resources/${encodeURIComponent(r)}`;
export const annotationsApi = {
  list: (a: string, t: string, r: string, after = 0) =>
    request<{
      items: FileAnnotation[];
      has_more: boolean;
      next_cursor: number;
    }>(`${resourceBase(a, t, r)}/annotations?after=${after}`),
  create: (
    a: string,
    t: string,
    r: string,
    version: string,
    anchor: FileAnchor,
    body: string,
  ) =>
    request<FileAnnotation>(`${resourceBase(a, t, r)}/annotations`, {
      method: "POST",
      body: JSON.stringify({ version, anchor, body }),
    }),
  update: (
    a: string,
    t: string,
    r: string,
    id: string,
    revision: number,
    changes: { status?: string; reply?: string },
  ) =>
    request<FileAnnotation>(
      `${resourceBase(a, t, r)}/annotations/${encodeURIComponent(id)}`,
      { method: "PATCH", body: JSON.stringify({ revision, ...changes }) },
    ),
  requests: (a: string, t: string, r: string) =>
    request<{ items: ModificationRequest[] }>(
      `${resourceBase(a, t, r)}/annotation-requests`,
    ),
  submit: (
    a: string,
    t: string,
    payload: {
      command_id: string;
      resource_id: string;
      source_version: string;
      annotations: { annotation_id: string; revision: number }[];
    },
  ) =>
    request<ModificationRequest>(`${fileScope(a, t)}/annotation-requests`, {
      method: "POST",
      body: JSON.stringify(payload),
    }),
};
