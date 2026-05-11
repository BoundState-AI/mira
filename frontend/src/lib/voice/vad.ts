// Energy-based VAD with adaptive noise floor.
//
// Tracks a slow-moving baseline of frame RMS; treats sustained excursions
// above (baseline + margin) as speech, and the absence of such frames for
// HANGOVER_MS as the utterance boundary. Sufficient for the demo path with
// headset + getUserMedia echoCancellation / noiseSuppression on.
//
// If the demo room turns out to be acoustically rough, swap this for
// @ricky0123/vad-web (Silero ONNX). The interface here is identical.

const FRAME_MS = 20;
const SPEECH_TRIGGER_FRAMES = 3;     // 60ms above threshold to enter speech
const HANGOVER_FRAMES = 30;          // 600ms below threshold to end speech
const BASELINE_ALPHA = 0.02;         // EMA constant for noise floor
const MIN_THRESHOLD = 0.012;
const MARGIN = 0.018;
const MAX_UTTERANCE_FRAMES = 60 * 1000 / FRAME_MS; // 60 seconds

export type VadEvent = "speech-start" | "speech-end";

export interface VadCallbacks {
  onEvent: (event: VadEvent) => void;
}

export class EnergyVad {
  private baseline = 0.005;
  private aboveCount = 0;
  private belowCount = 0;
  private speaking = false;
  private utteranceFrames = 0;
  private suspended = false;
  private readonly callbacks: VadCallbacks;

  constructor(callbacks: VadCallbacks) {
    this.callbacks = callbacks;
  }

  /** Suspend VAD output (e.g. while TTS is playing) to prevent echo-triggered detection. */
  setSuspended(value: boolean): void {
    if (value === this.suspended) return;
    this.suspended = value;
    if (value && this.speaking) {
      this.endUtterance();
    }
  }

  feed(rms: number): void {
    if (this.suspended) {
      this.baseline = this.baseline * (1 - BASELINE_ALPHA) + rms * BASELINE_ALPHA;
      return;
    }

    const threshold = Math.max(MIN_THRESHOLD, this.baseline + MARGIN);

    if (rms > threshold) {
      this.aboveCount += 1;
      this.belowCount = 0;
      if (!this.speaking && this.aboveCount >= SPEECH_TRIGGER_FRAMES) {
        this.speaking = true;
        this.utteranceFrames = 0;
        this.callbacks.onEvent("speech-start");
      }
    } else {
      this.aboveCount = 0;
      this.belowCount += 1;
      // Baseline only updates on silence frames so speech doesn't drag it up.
      this.baseline = this.baseline * (1 - BASELINE_ALPHA) + rms * BASELINE_ALPHA;
      if (this.speaking && this.belowCount >= HANGOVER_FRAMES) {
        this.endUtterance();
      }
    }

    if (this.speaking) {
      this.utteranceFrames += 1;
      if (this.utteranceFrames >= MAX_UTTERANCE_FRAMES) {
        this.endUtterance();
      }
    }
  }

  reset(): void {
    this.speaking = false;
    this.aboveCount = 0;
    this.belowCount = 0;
    this.utteranceFrames = 0;
  }

  get isSpeaking(): boolean {
    return this.speaking;
  }

  private endUtterance(): void {
    this.speaking = false;
    this.aboveCount = 0;
    this.belowCount = 0;
    this.utteranceFrames = 0;
    this.callbacks.onEvent("speech-end");
  }
}
