const API_BASE = "/api/chat";

export interface MiraChatMessage {
  role: "user" | "assistant";
  content: string;
  engine_used?: string | null;
  entities?: Record<string, unknown>;
}

export interface MiraChatRequest {
  message: string;
  session_id?: string | null;
  history?: MiraChatMessage[];
  module_context?: Record<string, unknown> | null;
}

export interface MiraChatResponse {
  response: string;
  session_id: string;
  engine_used?: string | null;
  verdict?: string | null;
  audit_id?: string | null;
  follow_up_suggestions: string[];
  mode?: "answer_only" | "draft_artifact" | "review_existing" | null;
  entities: Record<string, unknown>;
}

export interface MiraChatPingResponse {
  status: string;
  domain: string;
  adapters_loaded: string;
}

function buildErrorMessage(statusText: string, detail: unknown): string {
  if (typeof detail === "string" && detail.trim()) {
    return detail;
  }
  if (detail && typeof detail === "object" && "detail" in detail) {
    const nestedDetail = (detail as { detail?: unknown }).detail;
    if (typeof nestedDetail === "string" && nestedDetail.trim()) {
      return nestedDetail;
    }
  }
  return `Chat request failed: ${statusText}`;
}

export async function fetchMiraChatPing(): Promise<MiraChatPingResponse> {
  const response = await fetch(`${API_BASE}/ping`);
  if (!response.ok) {
    throw new Error(`Chat ping failed: ${response.statusText}`);
  }
  return response.json();
}

export async function sendMiraChatMessage(payload: MiraChatRequest): Promise<MiraChatResponse> {
  const response = await fetch(`${API_BASE}/`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(buildErrorMessage(response.statusText, detail));
  }

  return response.json();
}
