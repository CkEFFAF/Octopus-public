import { getApiUrl } from "../config";
import type { SharedMessage } from "./threadShares";

export interface PublicThreadShare {
  title: string;
  timezone: string;
  created_at: number;
  expires_at: number | null;
  messages: SharedMessage[];
}

/** Independent of the authenticated request client and its login redirects. */
export async function readPublicThreadShare(
  token: string,
  signal?: AbortSignal,
): Promise<PublicThreadShare> {
  if (!/^[A-Za-z0-9_-]{43}$/.test(token)) throw new Error("share_unavailable");
  const response = await fetch(
    getApiUrl(`/public/thread-shares/${encodeURIComponent(token)}`),
    {
      method: "GET",
      credentials: "omit",
      cache: "no-store",
      referrerPolicy: "no-referrer",
      redirect: "error",
      signal,
      headers: { Accept: "application/json" },
    },
  );
  if (!response.ok) throw new Error("share_unavailable");
  return response.json() as Promise<PublicThreadShare>;
}
