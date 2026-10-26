/** Ephemeral capture: no upload, persistence, speech recognition or scoring. */
export class BrowserReadingRecorder {
  private stream: MediaStream | null = null;
  private recorder: MediaRecorder | null = null;
  private generation = 0;
  private url: string | null = null;
  private watchdog: ReturnType<typeof setTimeout> | null = null;

  constructor(private readonly maximumMs = 120_000) {}

  get supported(): boolean {
    return Boolean(
      window.isSecureContext &&
      typeof navigator.mediaDevices?.getUserMedia === 'function' &&
      window.MediaRecorder,
    );
  }

  async start(onStopped: (url: string) => void, onError: () => void): Promise<void> {
    this.discard();
    if (!this.supported) throw new Error('MICROPHONE_UNSUPPORTED');
    const generation = this.generation;
    const stream = await navigator.mediaDevices.getUserMedia({ audio: true, video: false });
    if (generation !== this.generation || document.hidden) {
      stream.getTracks().forEach((track) => track.stop());
      throw new DOMException('Recording cancelled', 'AbortError');
    }
    this.stream = stream;
    const chunks: Blob[] = [];
    try {
      const recorder = new MediaRecorder(stream);
      this.recorder = recorder;
      recorder.ondataavailable = (event) => {
        if (event.data.size) chunks.push(event.data);
      };
      recorder.onerror = () => {
        if (generation !== this.generation) return;
        this.discard();
        onError();
      };
      recorder.onstop = () => {
        if (generation !== this.generation) return;
        this.releaseTracks();
        const blob = new Blob(chunks, { type: recorder.mimeType });
        if (!blob.size) {
          onError();
          return;
        }
        this.url = URL.createObjectURL(blob);
        onStopped(this.url);
      };
      recorder.start();
      // Memory/device protection only; no countdown or learning deadline.
      this.watchdog = setTimeout(() => this.stop(), this.maximumMs);
    } catch (error) {
      this.discard();
      throw error;
    }
  }

  stop(): void {
    if (this.recorder?.state === 'recording') {
      this.recorder.stop();
      this.releaseTracks();
    }
  }

  discard(): void {
    this.generation += 1;
    this.stop();
    this.recorder = null;
    this.releaseTracks();
    if (this.url) URL.revokeObjectURL(this.url);
    this.url = null;
  }

  private releaseTracks(): void {
    if (this.watchdog) clearTimeout(this.watchdog);
    this.watchdog = null;
    this.stream?.getTracks().forEach((track) => track.stop());
    this.stream = null;
  }
}
