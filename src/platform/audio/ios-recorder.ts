import { nativeOperation } from '../ios-app';
import type { ShopCapture } from './browser-shop-recorder';

let sequence = 0;

export class IOSShopRecorder implements ShopCapture {
  private id: string | null = null;

  constructor(private readonly limit = 5000) {}

  async start() {
    this.discard();
    const id = `recording-${++sequence}`;
    this.id = id;
    try {
      await nativeOperation('recordStart', { id, limit: this.limit });
      if (this.id !== id) throw new DOMException('Cancelled', 'AbortError');
    } catch (error) {
      if (this.id === id) this.discard();
      throw error;
    }
  }

  async snapshot(stop = false): Promise<Blob | null> {
    const id = this.id;
    if (!id) return null;
    const data = await nativeOperation<string | null>(stop ? 'recordStop' : 'recordSnapshot', {
      id,
    });
    if (this.id !== id) return null;
    if (stop) this.id = null;
    if (!data) return null;
    const bytes = Uint8Array.from(atob(data), (character) => character.charCodeAt(0));
    return new Blob([bytes], { type: 'audio/wav' });
  }

  async level(): Promise<number> {
    const id = this.id;
    return id ? nativeOperation<number>('recordLevel', { id }) : 0;
  }

  discard() {
    const id = this.id;
    this.id = null;
    if (id) void nativeOperation('recordDiscard', { id }).catch(() => undefined);
  }
}

export class IOSReadingRecorder {
  private capture = new IOSShopRecorder(30_000);
  private generation = 0;
  private url: string | null = null;
  private watchdog: ReturnType<typeof setTimeout> | null = null;
  private finish: (() => Promise<void>) | null = null;
  audio: Blob | null = null;

  async start(onStopped: (url: string) => void, onError: () => void): Promise<void> {
    this.discard();
    const generation = this.generation;
    await this.capture.start();
    if (generation !== this.generation) throw new DOMException('Cancelled', 'AbortError');
    this.finish = async () => {
      try {
        const blob = await this.capture.snapshot(true);
        if (generation !== this.generation) return;
        if (!blob) {
          onError();
          return;
        }
        this.audio = blob;
        this.url = URL.createObjectURL(blob);
        onStopped(this.url);
      } catch {
        if (generation === this.generation) onError();
      }
    };
    this.watchdog = setTimeout(() => this.stop(), 30_000);
  }

  stop() {
    if (this.watchdog) clearTimeout(this.watchdog);
    this.watchdog = null;
    const finish = this.finish;
    this.finish = null;
    void finish?.();
  }

  discard() {
    this.generation++;
    if (this.watchdog) clearTimeout(this.watchdog);
    this.watchdog = null;
    this.finish = null;
    this.capture.discard();
    if (this.url) URL.revokeObjectURL(this.url);
    this.url = null;
    this.audio = null;
  }
}
