// Streaming TTS audio player with barge-in support.
//
// Strategy: backend emits clauses; for each clause, we accumulate base64-decoded
// MP3 chunks until the audio_end signal, then decode the full clause with
// AudioContext.decodeAudioData and play it via AudioBufferSourceNode. Clauses
// are queued so playback is sequential.
//
// Barge-in: stop() immediately cancels playback, drops the queue, and disposes
// the active source — UI can call this when VAD detects the user speaking.

interface QueueEntry {
  text: string;
  bytes: Uint8Array[];
}

export interface AudioPlayerCallbacks {
  onSpeakingStart?: () => void;
  onSpeakingEnd?: () => void;
  onClauseSpoken?: (text: string) => void;
  onError?: (error: Error) => void;
}

export class StreamingAudioPlayer {
  private ctx: AudioContext | null = null;
  private queue: QueueEntry[] = [];
  private pending: QueueEntry | null = null;
  private playing = false;
  private currentSource: AudioBufferSourceNode | null = null;
  private currentGain: GainNode | null = null;
  private readonly callbacks: AudioPlayerCallbacks;

  constructor(callbacks: AudioPlayerCallbacks = {}) {
    this.callbacks = callbacks;
  }

  ensureContext(): AudioContext {
    if (!this.ctx || this.ctx.state === "closed") {
      this.ctx = new AudioContext({ latencyHint: "interactive" });
    }
    if (this.ctx.state === "suspended") {
      void this.ctx.resume();
    }
    return this.ctx;
  }

  startClause(text: string): void {
    this.pending = { text, bytes: [] };
  }

  appendChunk(bytes: Uint8Array): void {
    if (!this.pending) {
      this.pending = { text: "", bytes: [] };
    }
    this.pending.bytes.push(bytes);
  }

  endClause(): void {
    if (!this.pending) return;
    if (this.pending.bytes.length === 0) {
      this.pending = null;
      return;
    }
    this.queue.push(this.pending);
    this.pending = null;
    void this.drain();
  }

  /** Barge-in: immediately stop and discard everything. */
  stop(): void {
    this.queue = [];
    this.pending = null;
    if (this.currentSource) {
      try {
        this.currentSource.stop();
      } catch {}
      try {
        this.currentSource.disconnect();
      } catch {}
      this.currentSource = null;
    }
    if (this.currentGain) {
      try {
        this.currentGain.disconnect();
      } catch {}
      this.currentGain = null;
    }
    if (this.playing) {
      this.playing = false;
      this.callbacks.onSpeakingEnd?.();
    }
  }

  async close(): Promise<void> {
    this.stop();
    if (this.ctx && this.ctx.state !== "closed") {
      await this.ctx.close().catch(() => undefined);
    }
    this.ctx = null;
  }

  get isSpeaking(): boolean {
    return this.playing;
  }

  private async drain(): Promise<void> {
    if (this.playing) return;
    const next = this.queue.shift();
    if (!next) return;

    this.playing = true;
    this.callbacks.onSpeakingStart?.();

    const ctx = this.ensureContext();
    try {
      const totalLength = next.bytes.reduce((acc, view) => acc + view.byteLength, 0);
      const merged = new Uint8Array(totalLength);
      let offset = 0;
      for (const view of next.bytes) {
        merged.set(view, offset);
        offset += view.byteLength;
      }

      const audioBuffer = await ctx.decodeAudioData(merged.buffer.slice(0));
      const source = ctx.createBufferSource();
      source.buffer = audioBuffer;
      const gain = ctx.createGain();
      gain.gain.value = 1;
      source.connect(gain).connect(ctx.destination);

      this.currentSource = source;
      this.currentGain = gain;

      await new Promise<void>((resolve) => {
        source.onended = () => resolve();
        try {
          source.start();
        } catch (err) {
          this.callbacks.onError?.(err as Error);
          resolve();
        }
      });

      this.callbacks.onClauseSpoken?.(next.text);
    } catch (err) {
      this.callbacks.onError?.(err as Error);
    } finally {
      this.currentSource = null;
      this.currentGain = null;
      this.playing = false;
      if (this.queue.length > 0) {
        void this.drain();
      } else {
        this.callbacks.onSpeakingEnd?.();
      }
    }
  }
}

export function decodeBase64Chunk(b64: string): Uint8Array {
  const binary = atob(b64);
  const bytes = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i += 1) {
    bytes[i] = binary.charCodeAt(i);
  }
  return bytes;
}

export function encodePcmFrameToBase64(buffer: ArrayBuffer): string {
  const bytes = new Uint8Array(buffer);
  let binary = "";
  const chunkSize = 0x8000;
  for (let i = 0; i < bytes.length; i += chunkSize) {
    binary += String.fromCharCode.apply(null, bytes.subarray(i, i + chunkSize) as unknown as number[]);
  }
  return btoa(binary);
}
