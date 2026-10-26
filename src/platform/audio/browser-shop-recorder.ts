/** Local bounded PCM capture for MATCH-10 snapshots. No MediaRecorder chunk decoding or storage. */
export interface ShopCapture {
  start(): Promise<void>;
  snapshot(): Blob | null;
  discard(): void;
}

/** Average source-rate bins into 16kHz mono PCM16 WAV; samples never leave this port as URLs. */
export function shopPcmWav(samples: Float32Array, sourceRate: number): Blob {
  const rate = 16000;
  const length = Math.floor((samples.length * rate) / sourceRate);
  const bytes = new ArrayBuffer(44 + length * 2);
  const view = new DataView(bytes);
  const text = (offset: number, value: string) => {
    for (let i = 0; i < value.length; i++) view.setUint8(offset + i, value.charCodeAt(i));
  };
  text(0, 'RIFF');
  view.setUint32(4, 36 + length * 2, true);
  text(8, 'WAVE');
  text(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, rate, true);
  view.setUint32(28, rate * 2, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, 'data');
  view.setUint32(40, length * 2, true);
  for (let i = 0; i < length; i++) {
    const start = Math.floor((i * sourceRate) / rate);
    const end = Math.min(
      samples.length,
      Math.max(start + 1, Math.floor(((i + 1) * sourceRate) / rate)),
    );
    let sample = 0;
    for (let j = start; j < end; j++) sample += samples[j]!;
    sample = Math.max(-1, Math.min(1, sample / (end - start)));
    view.setInt16(44 + i * 2, Math.round(sample * (sample < 0 ? 32768 : 32767)), true);
  }
  return new Blob([bytes], { type: 'audio/wav' });
}

export class BrowserShopRecorder implements ShopCapture {
  private epoch = 0;
  private context: AudioContext | null = null;
  private stream: MediaStream | null = null;
  private source: MediaStreamAudioSourceNode | null = null;
  private processor: ScriptProcessorNode | null = null;
  private sink: GainNode | null = null;
  private samples: Float32Array | null = null;
  private frames = 0;
  private watchdog: ReturnType<typeof setTimeout> | null = null;
  constructor(private readonly maximumMs: number) {}

  async start(): Promise<void> {
    this.discard();
    if (!window.isSecureContext || !navigator.mediaDevices?.getUserMedia || !window.AudioContext)
      throw new Error('MICROPHONE_UNSUPPORTED');
    const generation = this.epoch;
    const context = new AudioContext();
    this.context = context;
    // Resume from the commodity click gesture, including Safari's activation requirement.
    const resumed = context.resume();
    void resumed.catch(() => undefined);
    try {
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: { channelCount: 1, echoCancellation: true, noiseSuppression: true },
        video: false,
      });
      if (generation !== this.epoch || document.hidden) {
        stream.getTracks().forEach((track) => track.stop());
        throw new DOMException('cancelled', 'AbortError');
      }
      this.stream = stream;
      await resumed;
      if (generation !== this.epoch) throw new DOMException('cancelled', 'AbortError');
      this.samples = new Float32Array(Math.ceil((context.sampleRate * this.maximumMs) / 1000));
      this.frames = 0;
      this.source = context.createMediaStreamSource(stream);
      // Widely supported native PCM callback; the output is silent and never monitors the mic.
      this.processor = context.createScriptProcessor(2048, 1, 1);
      this.sink = context.createGain();
      this.sink.gain.value = 0;
      this.processor.onaudioprocess = (event) => {
        if (generation !== this.epoch || !this.samples) return;
        const chunk = event.inputBuffer.getChannelData(0);
        const take = Math.min(chunk.length, this.samples.length - this.frames);
        this.samples.set(chunk.subarray(0, take), this.frames);
        this.frames += take;
      };
      this.source.connect(this.processor);
      this.processor.connect(this.sink);
      this.sink.connect(context.destination);
      // Independent protection if UI/session code ever fails to dispose capture.
      this.watchdog = setTimeout(() => this.discard(), this.maximumMs + 100);
    } catch (error) {
      if (generation === this.epoch) this.discard();
      // Resume can reject after cancellation/permission denial; always consume it.
      void resumed.catch(() => undefined);
      throw error;
    }
  }
  snapshot(): Blob | null {
    if (!this.samples || !this.context || this.frames === 0) return null;
    return shopPcmWav(this.samples.subarray(0, this.frames), this.context.sampleRate);
  }
  discard(): void {
    this.epoch += 1;
    if (this.watchdog) clearTimeout(this.watchdog);
    this.watchdog = null;
    if (this.processor) this.processor.onaudioprocess = null;
    this.source?.disconnect();
    this.processor?.disconnect();
    this.sink?.disconnect();
    this.stream?.getTracks().forEach((track) => track.stop());
    if (this.context && this.context.state !== 'closed')
      void this.context.close().catch(() => undefined);
    this.context = null;
    this.stream = null;
    this.processor = null;
    this.source = null;
    this.sink = null;
    this.samples = null;
    this.frames = 0;
  }
}
