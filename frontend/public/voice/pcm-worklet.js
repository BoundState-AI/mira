// PCM downsampler AudioWorkletProcessor.
// Captures microphone audio at the AudioContext's native sample rate and
// emits 16 kHz mono Int16 PCM frames to the main thread for transport.
//
// Implementation notes:
//   - Polyphase resampling is overkill for speech; a simple linear-interpolation
//     downsample is sufficient for STT input quality.
//   - Frames are buffered to FRAME_SAMPLES (320 = 20ms @ 16kHz) before posting
//     to balance throughput vs message overhead.

const TARGET_RATE = 16000;
const FRAME_SAMPLES = 320; // 20ms @ 16kHz

class PcmDownsampleProcessor extends AudioWorkletProcessor {
  constructor() {
    super();
    this.ratio = sampleRate / TARGET_RATE;
    this.cursor = 0;
    this.buffer = new Int16Array(FRAME_SAMPLES);
    this.bufferIdx = 0;
  }

  process(inputs) {
    const input = inputs[0];
    if (!input || input.length === 0) return true;
    const channel = input[0];
    if (!channel) return true;

    let pos = this.cursor;
    while (pos < channel.length) {
      const idx = Math.floor(pos);
      const frac = pos - idx;
      const next = idx + 1 < channel.length ? channel[idx + 1] : channel[idx];
      const sample = channel[idx] * (1 - frac) + next * frac;
      const clamped = Math.max(-1, Math.min(1, sample));
      this.buffer[this.bufferIdx++] = clamped < 0 ? clamped * 0x8000 : clamped * 0x7fff;

      if (this.bufferIdx >= FRAME_SAMPLES) {
        this.port.postMessage(this.buffer.slice(0, this.bufferIdx).buffer, [this.buffer.slice(0, this.bufferIdx).buffer]);
        this.bufferIdx = 0;
      }
      pos += this.ratio;
    }
    this.cursor = pos - channel.length;
    return true;
  }
}

registerProcessor("pcm-downsample-processor", PcmDownsampleProcessor);
