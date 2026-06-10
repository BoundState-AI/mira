import type { RecentAuditResponse, UserIdentity } from "./types";

const API_BASE = "/api/chat";

// Identity is stable for the lifetime of the auth session, and the PIV chip
// mounts on every dock open — cache the in-flight/settled promise so repeated
// mounts share one request. Failures clear the cache so the next mount retries.
let whoamiPromise: Promise<UserIdentity> | null = null;

export async function fetchWhoami(): Promise<UserIdentity> {
  if (!whoamiPromise) {
    whoamiPromise = (async () => {
      const response = await fetch(`${API_BASE}/whoami`);
      if (!response.ok) {
        throw new Error(`whoami failed: ${response.statusText}`);
      }
      return (await response.json()) as UserIdentity;
    })().catch((err) => {
      whoamiPromise = null;
      throw err;
    });
  }
  return whoamiPromise;
}

export async function fetchRecentAudit(opts: {
  limit?: number;
  sessionId?: string | null;
} = {}): Promise<RecentAuditResponse> {
  const params = new URLSearchParams();
  if (opts.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts.sessionId) params.set("session_id", opts.sessionId);
  const qs = params.toString();
  const url = qs ? `${API_BASE}/audit/recent?${qs}` : `${API_BASE}/audit/recent`;
  const response = await fetch(url);
  if (!response.ok) {
    throw new Error(`audit/recent failed: ${response.statusText}`);
  }
  return response.json();
}
