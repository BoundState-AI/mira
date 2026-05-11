export type VoiceState =
  | "idle"
  | "connecting"
  | "ready"
  | "listening"
  | "thinking"
  | "speaking"
  | "error";

export interface VoiceGreeting {
  text: string;
  step_key: string | null;
  step_label: string | null;
  blockers: string[];
}

export interface VoiceConfigInfo {
  enabled: boolean;
  demo_mode: boolean;
  stt_provider: string;
  tts_provider: string;
  active_sessions: number;
  max_concurrent_sessions: number;
  has_real_stt: boolean;
  has_real_tts: boolean;
}

export interface VoiceListEntry {
  voice_id: string;
  name: string;
  engine: string;
  language?: string;
  gender?: string;
}

export interface VoiceListResponse {
  provider: string;
  voices: VoiceListEntry[];
  demo_mode: boolean;
  default_voice_id: string;
}

export interface VoiceTurnSummary {
  userTranscript: string;
  assistantText: string;
  engineUsed: string | null;
  verdict: string | null;
  auditId: string | null;
  followUps: string[];
  entities: Record<string, unknown>;
}

export interface VoiceClientCallbacks {
  onStateChange?: (state: VoiceState) => void;
  onTranscript?: (text: string) => void;
  onAssistantDelta?: (delta: string) => void;
  onAssistantMeta?: (meta: { engineId: string | null; verdict: string | null }) => void;
  onTurnComplete?: (summary: VoiceTurnSummary) => void;
  onError?: (error: string) => void;
}
