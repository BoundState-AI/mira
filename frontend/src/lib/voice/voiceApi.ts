import type { MiraChatMessage } from "@/lib/chat-api";
import type { VoiceConfigInfo, VoiceGreeting, VoiceListResponse } from "./types";

const API_BASE = "/api/chat";

export async function fetchVoiceStatus(): Promise<VoiceConfigInfo> {
  const response = await fetch(`${API_BASE}/voice/status`);
  if (!response.ok) {
    throw new Error(`voice/status failed: ${response.statusText}`);
  }
  return response.json();
}

export async function fetchVoiceList(): Promise<VoiceListResponse> {
  const response = await fetch(`${API_BASE}/voice/voices`);
  if (!response.ok) {
    throw new Error(`voice/voices failed: ${response.statusText}`);
  }
  return response.json();
}

export interface PresenceRequest {
  module_context: Record<string, unknown> | null;
  session_id?: string | null;
  history?: MiraChatMessage[];
}

export async function fetchPresenceGreeting(
  payload: PresenceRequest,
): Promise<VoiceGreeting | null> {
  const response = await fetch(`${API_BASE}/presence`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!response.ok) {
    throw new Error(`presence failed: ${response.statusText}`);
  }
  const data = (await response.json()) as { greeting: VoiceGreeting | null };
  return data.greeting ?? null;
}
