// VoiceClient — orchestrates the full two-way voice loop.
//
//   ┌── AudioCapture (mic → 16kHz Int16 PCM frames) ──┐
//   │                                                  ▼
//   │   EnergyVad ──────────┐               WebSocket  │
//   │                       │                          │
//   │                       │ speech-start/end  send → │
//   │                       │                          │
//   └───────────────────────┴── frames during speech ──┘
//                                       │
//                                       ▼
//          server: STT → chat pipeline → TTS audio chunks
//                                       │
//                                       ▼
//                       StreamingAudioPlayer (decode + play)
//
// Barge-in: when VAD fires speech-start while we're SPEAKING, we:
//   1) stop the player immediately
//   2) send {type: "interrupt"} to the server (cancels TTS + chat stream)
//   3) flip back to LISTENING and start a new utterance buffer

import type { MiraChatMessage } from "@/lib/chat-api";
import { AudioCapture, type CaptureFrame } from "./audioCapture";
import { decodeBase64Chunk, encodePcmFrameToBase64, StreamingAudioPlayer } from "./audioPlayer";
import { EnergyVad } from "./vad";
import type {
  VoiceClientCallbacks,
  VoiceState,
  VoiceTurnSummary,
} from "./types";

export interface VoiceClientOptions extends VoiceClientCallbacks {
  endpoint?: string;
  voiceId?: string | null;
  chatSessionId?: string | null;
  moduleContext?: Record<string, unknown> | null;
  history?: MiraChatMessage[];
  authToken?: string | null;
}

function defaultEndpoint(): string {
  if (typeof window === "undefined") return "/api/chat/voice";
  const proto = window.location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${window.location.host}/api/chat/voice`;
}

export class VoiceClient {
  private ws: WebSocket | null = null;
  private capture: AudioCapture | null = null;
  private vad: EnergyVad | null = null;
  private player = new StreamingAudioPlayer({
    onSpeakingStart: () => {
      this.vad?.setSuspended(true);
    },
    onSpeakingEnd: () => {
      // Slight delay before unmuting VAD lets the room tail settle.
      window.setTimeout(() => this.vad?.setSuspended(false), 200);
    },
  });

  private state: VoiceState = "idle";
  private options: VoiceClientOptions;
  private currentTurn = {
    transcript: "",
    assistantText: "",
    engineUsed: null as string | null,
    verdict: null as string | null,
  };
  private capturingUtterance = false;
  private intentionalClose = false;
  private chatSessionId: string | null;
  private history: MiraChatMessage[];

  constructor(options: VoiceClientOptions) {
    this.options = options;
    this.chatSessionId = options.chatSessionId ?? null;
    this.history = options.history ? [...options.history] : [];
  }

  get currentState(): VoiceState {
    return this.state;
  }

  async start(): Promise<void> {
    if (this.state !== "idle" && this.state !== "error") {
      return;
    }
    this.setState("connecting");

    await this.openWebSocket();
    this.vad = new EnergyVad({ onEvent: (event) => this.onVadEvent(event) });
    this.capture = new AudioCapture({
      onFrame: (frame) => this.onCaptureFrame(frame),
      onError: (err) => this.fail(err.message),
    });

    try {
      await this.capture.start();
    } catch (err) {
      // Close the socket too, or the server holds a concurrency slot for a
      // session that will never send audio.
      this.intentionalClose = true;
      this.ws?.close();
      this.ws = null;
      this.fail(`Microphone error: ${(err as Error).message}`);
      return;
    }

    this.sendJson({
      type: "start",
      voice_id: this.options.voiceId ?? null,
      chat_session_id: this.chatSessionId,
      module_context: this.options.moduleContext ?? null,
      history: this.history,
    });
  }

  async stop(): Promise<void> {
    // Mark before closing so the onclose handler doesn't surface a
    // spurious "WebSocket closed" error for a user-initiated stop.
    this.intentionalClose = true;
    this.capturingUtterance = false;
    if (this.ws && this.ws.readyState === WebSocket.OPEN) {
      try {
        this.ws.send(JSON.stringify({ type: "end" }));
      } catch {}
    }
    this.ws?.close();
    this.ws = null;
    await this.capture?.stop();
    this.capture = null;
    this.vad = null;
    this.player.stop();
    this.setState("idle");
  }

  /** Manual interrupt (e.g. user clicked a stop button). */
  interrupt(): void {
    if (this.state !== "speaking") return;
    this.player.stop();
    this.sendJson({ type: "interrupt" });
    this.setState("listening");
  }

  setVoiceId(voiceId: string | null): void {
    this.options.voiceId = voiceId;
    this.sendJson({ type: "update_context", voice_id: voiceId });
  }

  setModuleContext(context: Record<string, unknown> | null): void {
    // Pages rebuild this object every render; only forward genuine changes
    // so the WebSocket isn't spammed on unrelated re-renders.
    const serialized = JSON.stringify(context ?? null);
    if (serialized === JSON.stringify(this.options.moduleContext ?? null)) {
      return;
    }
    this.options.moduleContext = context;
    // Forward live so mid-session step changes (e.g. galvanic moving from
    // define_material_couple to review_galvanic_screen) reach the server
    // before the next voice turn.
    this.sendJson({ type: "update_context", module_context: context });
  }

  setHistory(history: MiraChatMessage[]): void {
    this.history = [...history];
  }

  // ---- WebSocket ----

  private openWebSocket(): Promise<void> {
    return new Promise((resolve, reject) => {
      const url = this.options.endpoint ?? defaultEndpoint();
      const finalUrl = this.options.authToken
        ? `${url}${url.includes("?") ? "&" : "?"}token=${encodeURIComponent(this.options.authToken)}`
        : url;
      let ws: WebSocket;
      try {
        ws = new WebSocket(finalUrl);
      } catch (err) {
        reject(err);
        return;
      }
      ws.binaryType = "arraybuffer";
      this.ws = ws;
      ws.onopen = () => resolve();
      ws.onerror = () => {
        // The 'close' handler will pick up the actual reason.
      };
      ws.onclose = (event) => {
        if (this.intentionalClose) return;
        if (this.state === "connecting") {
          reject(new Error(`Voice WebSocket closed (${event.code})`));
        } else if (this.state !== "idle") {
          this.fail(`Voice WebSocket closed (${event.code})`);
        }
      };
      ws.onmessage = (event) => this.onWsMessage(event);
    });
  }

  private sendJson(payload: Record<string, unknown>): void {
    if (!this.ws || this.ws.readyState !== WebSocket.OPEN) return;
    try {
      this.ws.send(JSON.stringify(payload));
    } catch {}
  }

  private onWsMessage(event: MessageEvent): void {
    if (typeof event.data !== "string") return;
    let payload: { type?: string } & Record<string, unknown>;
    try {
      payload = JSON.parse(event.data);
    } catch {
      return;
    }

    switch (payload.type) {
      case "ready":
        this.setState("ready");
        break;
      case "state": {
        const next = payload.state as VoiceState | undefined;
        if (next === "listening" || next === "thinking" || next === "speaking" || next === "ready") {
          this.setState(next);
        }
        break;
      }
      case "transcript_final": {
        const text = typeof payload.text === "string" ? payload.text : "";
        this.currentTurn.transcript = text;
        this.options.onTranscript?.(text);
        break;
      }
      case "transcript_empty":
        this.setState("ready");
        break;
      case "assistant_meta": {
        const engineId = typeof payload.engine_id === "string" ? payload.engine_id : null;
        const verdict = typeof payload.verdict === "string" ? payload.verdict : null;
        this.currentTurn.engineUsed = engineId;
        this.currentTurn.verdict = verdict;
        this.options.onAssistantMeta?.({ engineId, verdict });
        break;
      }
      case "assistant_text": {
        const delta = typeof payload.delta === "string" ? payload.delta : "";
        if (!delta) break;
        this.currentTurn.assistantText += delta;
        this.options.onAssistantDelta?.(delta);
        break;
      }
      case "audio_start": {
        const text = typeof payload.text === "string" ? payload.text : "";
        this.player.startClause(text);
        break;
      }
      case "audio": {
        const data = typeof payload.data === "string" ? payload.data : "";
        if (data) this.player.appendChunk(decodeBase64Chunk(data));
        break;
      }
      case "audio_end":
        this.player.endClause();
        break;
      case "turn_done": {
        const auditId = typeof payload.audit_id === "string" ? payload.audit_id : null;
        const sessionId = typeof payload.session_id === "string" ? payload.session_id : null;
        if (sessionId) this.chatSessionId = sessionId;
        const followUps = Array.isArray(payload.follow_ups)
          ? (payload.follow_ups as unknown[]).filter((item): item is string => typeof item === "string")
          : [];
        const entities = typeof payload.entities === "object" && payload.entities
          ? (payload.entities as Record<string, unknown>)
          : {};
        const summary: VoiceTurnSummary = {
          userTranscript: this.currentTurn.transcript,
          assistantText: this.currentTurn.assistantText,
          engineUsed: this.currentTurn.engineUsed,
          verdict: this.currentTurn.verdict,
          auditId,
          followUps,
          entities,
        };
        this.history.push(
          { role: "user", content: summary.userTranscript },
          {
            role: "assistant",
            content: summary.assistantText,
            engine_used: summary.engineUsed ?? undefined,
            entities: summary.entities,
          },
        );
        if (this.history.length > 20) {
          this.history = this.history.slice(-20);
        }
        this.options.onTurnComplete?.(summary);
        this.currentTurn = {
          transcript: "",
          assistantText: "",
          engineUsed: null,
          verdict: null,
        };
        break;
      }
      case "interrupted":
        this.setState("listening");
        break;
      case "turn_cancelled":
        this.player.stop();
        this.setState("ready");
        break;
      case "error": {
        const detail = typeof payload.detail === "string" ? payload.detail : "voice error";
        this.options.onError?.(detail);
        break;
      }
      default:
        break;
    }
  }

  // ---- Capture → VAD → upload ----

  private onCaptureFrame(frame: CaptureFrame): void {
    this.vad?.feed(frame.rms);
    if (!this.capturingUtterance) return;
    this.sendJson({
      type: "audio",
      data: encodePcmFrameToBase64(frame.pcm),
    });
  }

  private onVadEvent(event: "speech-start" | "speech-end"): void {
    if (event === "speech-start") {
      // Barge-in path
      if (this.state === "speaking") {
        this.player.stop();
        this.sendJson({ type: "interrupt" });
      }
      this.capturingUtterance = true;
      this.setState("listening");
      return;
    }

    if (!this.capturingUtterance) return;
    this.capturingUtterance = false;
    this.sendJson({ type: "utterance_end" });
  }

  private setState(next: VoiceState): void {
    if (next === this.state) return;
    this.state = next;
    this.options.onStateChange?.(next);
  }

  private fail(message: string): void {
    this.options.onError?.(message);
    this.setState("error");
  }
}
