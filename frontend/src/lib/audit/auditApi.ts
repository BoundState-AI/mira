import type { RecentAuditResponse, UserIdentity } from "./types";

const API_BASE = "/api/chat";

export async function fetchWhoami(): Promise<UserIdentity> {
  const response = await fetch(`${API_BASE}/whoami`);
  if (!response.ok) {
    throw new Error(`whoami failed: ${response.statusText}`);
  }
  return response.json();
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
