// Microphone capture pipeline: getUserMedia → AudioWorklet → 16 kHz Int16 PCM frames.
//
// The AudioWorklet processor (public/voice/pcm-worklet.js) does the resampling
// off the main thread and posts ArrayBuffer frames; this module wraps the
// lifecycle (acquire / release device, gate frames during TTS playback to
// suppress echo, expose energy for the visualizer).

const WORKLET_URL = "/voice/pcm-worklet.js";

export interface CaptureFrame {
  pcm: ArrayBuffer;   // Int16 mono @ 16 kHz
  rms: number;        // 0..1 root-mean-square of the frame, for VAD/visualizer
}

export interface AudioCaptureOptions {
  onFrame: (frame: CaptureFrame) => void;
  onError?: (error: Error) => void;
  deviceId?: string;
}

export class AudioCapture {
  private ctx: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private worklet: AudioWorkletNode | null = null;
  private muted = false;
  private readonly options: AudioCaptureOptions;

  constructor(options: AudioCaptureOptions) {
    this.options = options;
  }

  async start(): Promise<void> {
    if (this.ctx) return;
    try {
      const constraints: MediaStreamConstraints = {
        audio: {
          channelCount: 1,
          echoCancellation: true,
          noiseSuppression: true,
          autoGainControl: true,
          ...(this.options.deviceId ? { deviceId: { exact: this.options.deviceId } } : {}),
        },
        video: false,
      };
      this.stream = await navigator.mediaDevices.getUserMedia(constraints);
      this.ctx = new AudioContext({ latencyHint: "interactive" });
      await this.ctx.audioWorklet.addModule(WORKLET_URL);
      this.source = this.ctx.createMediaStreamSource(this.stream);
      this.worklet = new AudioWorkletNode(this.ctx, "pcm-downsample-processor", {
        numberOfInputs: 1,
        numberOfOutputs: 0,
        channelCount: 1,
      });
      this.worklet.port.onmessage = (event: MessageEvent<ArrayBuffer>) => {
        if (this.muted) return;
        const buf = event.data;
        if (!(buf instanceof ArrayBuffer) || buf.byteLength === 0) return;
        this.options.onFrame({ pcm: buf, rms: computeRms(buf) });
      };
      this.source.connect(this.worklet);
    } catch (err) {
      this.options.onError?.(err as Error);
      await this.stop();
      throw err;
    }
  }

  async stop(): Promise<void> {
    try {
      this.worklet?.port.close();
    } catch {}
    this.worklet?.disconnect();
    this.source?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    if (this.ctx && this.ctx.state !== "closed") {
      await this.ctx.close().catch(() => undefined);
    }
    this.ctx = null;
    this.stream = null;
    this.source = null;
    this.worklet = null;
  }

  setMuted(value: boolean): void {
    this.muted = value;
  }

  get active(): boolean {
    return this.ctx !== null && !this.muted;
  }
}

function computeRms(buffer: ArrayBuffer): number {
  const view = new Int16Array(buffer);
  if (view.length === 0) return 0;
  let sum = 0;
  for (let i = 0; i < view.length; i += 1) {
    const v = view[i] / 0x8000;
    sum += v * v;
  }
  return Math.sqrt(sum / view.length);
}
