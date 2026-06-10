// Shared helpers for the two chat surfaces (full-page MiraChat and the
// floating MiraChatDock) plus the audit drawer. Keep presentation-free —
// pure data mapping only.

import type { MiraChatMessage } from "@/lib/chat-api";
import type { MiraChatStoredMessage, MiraModuleChatLaunchState } from "@/lib/mira-chat-context";

export const MAX_HISTORY_MESSAGES = 10;
export const MAX_STORED_MESSAGES = 24;

export type Verdict =
  | "PASS"
  | "CONDITIONAL_PASS"
  | "FAIL"
  | "REFUSE"
  | "INSUFFICIENT_DATA"
  | "ERROR"
  | null;

export type ChatUiMessage = MiraChatStoredMessage & { verdict?: Verdict };

export const ENGINE_LABELS: Record<string, string> = {
  knowledge_twins: "Knowledge Twins",
  miul: "MIUL Builder",
  mua: "MUA Writer",
  mp_plan: "M&P Plan",
  galvanic: "Galvanic",
  fracture: "Fracture Control",
  h2: "Hydrogen",
  oca: "Oxygen Compatibility",
  gpcm: "GPCM",
  maptis_search: "MAPTIS Search",
  forge_build: "FORGE Build",
  forge_explorer: "FORGE Explorer",
  tocr: "TOCR Review",
  bsmh: "MIRA",
};

export function verdictVariant(verdict: Verdict): "default" | "secondary" | "destructive" | "outline" {
  if (verdict === "PASS") return "default";
  if (verdict === "FAIL" || verdict === "ERROR" || verdict === "REFUSE") return "destructive";
  if (verdict === "CONDITIONAL_PASS") return "secondary";
  return "outline";
}

export function messageId(prefix: "user" | "assistant"): string {
  return `${prefix}-${Date.now()}-${Math.random().toString(16).slice(2, 8)}`;
}

export function toHistoryMessages(messages: ChatUiMessage[]): MiraChatMessage[] {
  return messages.slice(-MAX_HISTORY_MESSAGES).map((message) => ({
    role: message.role,
    content: message.content,
    engine_used: message.engineUsed ?? undefined,
    entities: message.entities,
  }));
}

export function assistantScopeLabel(
  activeModuleLaunchState: MiraModuleChatLaunchState | null,
  engineUsed?: string | null,
): string {
  if (activeModuleLaunchState?.moduleLabel) {
    return activeModuleLaunchState.moduleLabel;
  }
  if (engineUsed && ENGINE_LABELS[engineUsed]) {
    return ENGINE_LABELS[engineUsed];
  }
  return "MIRA";
}
