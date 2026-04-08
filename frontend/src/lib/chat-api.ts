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

export interface OraclePackSummary {
  pack_id: string;
  standard_id: string;
  standard_title: string;
  short_code?: string | null;
  rule_count: number;
  obligation_types: string[];
}

export interface OraclePackCatalogResponse {
  status: string;
  packs: OraclePackSummary[];
}

export interface OraclePackMutationResponse {
  status: string;
  slug: string;
  packs: OraclePackSummary[];
}

export interface MiraChatStreamEvent {
  type: string;
  [key: string]: unknown;
}

export interface MiraChatStreamCallbacks {
  onEvent?: (event: MiraChatStreamEvent) => void;
  signal?: AbortSignal;
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

export async function fetchOraclePackCatalog(): Promise<OraclePackCatalogResponse> {
  const response = await fetch(`${API_BASE}/oracle/packs`);
  if (!response.ok) {
    throw new Error(`Oracle pack catalog failed: ${response.statusText}`);
  }
  return response.json();
}

export async function refreshOraclePackCatalog(): Promise<OraclePackCatalogResponse> {
  const response = await fetch(`${API_BASE}/oracle/refresh`, { method: "POST" });
  if (!response.ok) {
    throw new Error(`Oracle pack refresh failed: ${response.statusText}`);
  }
  return response.json();
}

export async function importOraclePack(file: File): Promise<OraclePackMutationResponse> {
  const form = new FormData();
  form.append("pack_file", file);
  form.append("overwrite", "true");
  form.append("allow_partial", "true");

  const response = await fetch(`${API_BASE}/oracle/import-pack`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(buildErrorMessage(response.statusText, detail));
  }
  return response.json();
}

export async function ingestOraclePdf(args: {
  file: File;
  standardName?: string;
  forceType?: string;
  useVision?: boolean;
}): Promise<OraclePackMutationResponse> {
  const form = new FormData();
  form.append("source_file", args.file);
  form.append("overwrite", "true");
  form.append("allow_partial", "true");
  form.append("use_vision", args.useVision ? "true" : "false");
  if (args.standardName?.trim()) {
    form.append("standard_name", args.standardName.trim());
  }
  if (args.forceType?.trim()) {
    form.append("force_type", args.forceType.trim());
  }

  const response = await fetch(`${API_BASE}/oracle/ingest`, {
    method: "POST",
    body: form,
  });
  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(buildErrorMessage(response.statusText, detail));
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

function emitSseEvents(buffer: string, onEvent?: (event: MiraChatStreamEvent) => void): string {
  const normalized = buffer.replace(/\r\n/g, "\n");
  let cursor = 0;

  while (true) {
    const boundary = normalized.indexOf("\n\n", cursor);
    if (boundary === -1) {
      return normalized.slice(cursor);
    }

    const block = normalized.slice(cursor, boundary);
    cursor = boundary + 2;

    const dataLines = block
      .split("\n")
      .filter((line) => line.startsWith("data:"))
      .map((line) => line.slice(5).trimStart());

    if (!dataLines.length) {
      continue;
    }

    const rawData = dataLines.join("\n");
    const parsed = JSON.parse(rawData) as MiraChatStreamEvent;
    onEvent?.(parsed);
  }
}

export async function sendMiraChatStream(
  payload: MiraChatRequest,
  callbacks: MiraChatStreamCallbacks = {},
): Promise<void> {
  const response = await fetch(`${API_BASE}/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Accept: "text/event-stream",
    },
    body: JSON.stringify(payload),
    signal: callbacks.signal,
  });

  if (!response.ok) {
    const detail = await response.json().catch(() => null);
    throw new Error(buildErrorMessage(response.statusText, detail));
  }

  if (!response.body) {
    throw new Error("Chat stream failed: response body unavailable.");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

  while (true) {
    const { value, done } = await reader.read();
    if (done) {
      break;
    }

    buffer += decoder.decode(value, { stream: true });
    buffer = emitSseEvents(buffer, callbacks.onEvent);
  }

  buffer += decoder.decode();
  buffer = emitSseEvents(buffer, callbacks.onEvent);

  if (buffer.trim()) {
    throw new Error("Chat stream ended with an incomplete SSE event.");
  }
}
