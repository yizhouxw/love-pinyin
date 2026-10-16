/** Encoded learning assets only. Never receives recordings or household snapshots. */
export type ReadingPreparation = { total: number; ready: number; failed: number; bytes: number };
type Job = {
  source: string;
  foreground: boolean;
  controller: AbortController;
  promise: Promise<Blob>;
  resolve: (value: Blob) => void;
  reject: (error: unknown) => void;
};
const aborted = () => new DOMException('Reading audio cancelled.', 'AbortError');

export class ReadingAudioPool {
  private cache = new Map<string, Blob>();
  private jobs = new Map<string, Job>();
  private queue: Job[] = [];
  private active = 0;
  private generation = 0;
  private sources = new Set<string>();
  private failures = new Set<string>();
  private listeners = new Set<() => void>();
  private snapshot: ReadingPreparation = { total: 0, ready: 0, failed: 0, bytes: 0 };
  constructor(
    private budget = 16 * 1024 * 1024,
    private itemLimit = 128,
    private timeoutMs = 10000,
  ) {}
  status = () => this.snapshot;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  private notify() {
    this.snapshot = {
      total: this.sources.size,
      ready: [...this.sources].filter((source) => this.cache.has(source)).length,
      failed: this.failures.size,
      bytes: [...this.cache.values()].reduce((total, blob) => total + blob.size, 0),
    };
    queueMicrotask(() => this.listeners.forEach((listener) => listener()));
  }
  prepare(sources: string[]) {
    this.clear();
    this.sources = new Set(sources);
    for (const source of this.sources) void this.get(source).catch(() => undefined);
    this.notify();
  }
  prioritize(sources: string[]) {
    for (const source of [...sources].reverse()) {
      const index = this.queue.findIndex((job) => job.source === source);
      if (index >= 0) this.queue.unshift(...this.queue.splice(index, 1));
    }
  }
  retry() {
    for (const source of [...this.failures]) void this.get(source).catch(() => undefined);
  }
  get(source: string, foreground = false, signal?: AbortSignal): Promise<Blob> {
    if (signal?.aborted) return Promise.reject(aborted());
    const cached = this.cache.get(source);
    if (cached) {
      this.cache.delete(source);
      this.cache.set(source, cached);
      return Promise.resolve(cached);
    }
    let job = this.jobs.get(source);
    if (!job) {
      let resolve!: Job['resolve'];
      let reject!: Job['reject'];
      const promise = new Promise<Blob>((yes, no) => {
        resolve = yes;
        reject = no;
      });
      void promise.catch(() => undefined);
      job = { source, foreground, controller: new AbortController(), promise, resolve, reject };
      this.jobs.set(source, job);
      this.queue.push(job);
      this.failures.delete(source);
    }
    if (foreground) {
      job.foreground = true;
      this.prioritize([source]);
    }
    this.drain();
    if (!signal) return job.promise;
    const promise = job.promise;
    return new Promise((resolve, reject) => {
      const stop = () => {
        signal.removeEventListener('abort', stop);
        reject(aborted());
      };
      signal.addEventListener('abort', stop, { once: true });
      void promise.then(
        (value) => {
          signal.removeEventListener('abort', stop);
          if (signal.aborted) reject(aborted());
          else resolve(value);
        },
        (error) => {
          signal.removeEventListener('abort', stop);
          reject(error);
        },
      );
    });
  }
  private drain() {
    while (this.queue.length && this.active < (this.queue[0]!.foreground ? 3 : 2)) {
      const job = this.queue.shift()!;
      const generation = this.generation;
      this.active++;
      void this.download(job)
        .then((blob) => {
          if (generation !== this.generation || job.controller.signal.aborted) throw aborted();
          if (blob.size > this.budget) throw new Error('AUDIO_TOO_LARGE');
          while (
            this.cache.size >= this.itemLimit ||
            [...this.cache.values()].reduce((sum, value) => sum + value.size, 0) + blob.size >
              this.budget
          ) {
            const key = this.cache.keys().next().value;
            if (key === undefined) break;
            this.cache.delete(key);
            this.notify();
          }
          this.cache.set(job.source, blob);
          this.failures.delete(job.source);
          job.resolve(blob);
        })
        .catch((error) => {
          if (generation === this.generation && !job.controller.signal.aborted)
            this.failures.add(job.source);
          job.reject(error);
        })
        .finally(() => {
          if (generation === this.generation) {
            this.active--;
            this.jobs.delete(job.source);
            this.notify();
            this.drain();
          }
        });
    }
  }
  private async download(job: Job): Promise<Blob> {
    for (let attempt = 0; attempt < 2; attempt++) {
      const controller = new AbortController();
      const cancel = () => controller.abort();
      job.controller.signal.addEventListener('abort', cancel, { once: true });
      if (job.controller.signal.aborted) controller.abort();
      let timedOut = false;
      const timeout = setTimeout(() => {
        timedOut = true;
        controller.abort();
      }, this.timeoutMs);
      try {
        const response = await fetch(job.source, {
          credentials: 'same-origin',
          cache: 'no-store',
          signal: controller.signal,
        });
        if (!response.ok || response.status === 206)
          throw new Error(
            response.status >= 500 ? 'AUDIO_NETWORK' : `AUDIO_HTTP_${response.status}`,
          );
        const declared = Number(response.headers.get('Content-Length'));
        if (declared > 4 * 1024 * 1024) throw new Error('AUDIO_TOO_LARGE');
        const reader = response.body?.getReader();
        if (!reader) throw new Error('AUDIO_NETWORK');
        const chunks: Uint8Array<ArrayBuffer>[] = [];
        let size = 0;
        while (true) {
          const chunk = await reader.read();
          if (chunk.done) break;
          size += chunk.value.byteLength;
          if (size > 4 * 1024 * 1024) {
            await reader.cancel();
            throw new Error('AUDIO_TOO_LARGE');
          }
          chunks.push(new Uint8Array(chunk.value));
        }
        if (!size || (declared > 0 && declared !== size)) throw new Error('AUDIO_NETWORK');
        return new Blob(chunks, { type: response.headers.get('Content-Type') || 'audio/mpeg' });
      } catch (error) {
        if (job.controller.signal.aborted) throw aborted();
        const network =
          timedOut ||
          error instanceof TypeError ||
          (error instanceof Error && error.message === 'AUDIO_NETWORK');
        if (!network || attempt === 1)
          throw new Error(
            timedOut
              ? 'AUDIO_TIMEOUT'
              : network
                ? 'AUDIO_NETWORK'
                : error instanceof Error
                  ? error.message
                  : 'AUDIO_UNAVAILABLE',
            { cause: error },
          );
      } finally {
        clearTimeout(timeout);
        controller.abort();
        job.controller.signal.removeEventListener('abort', cancel);
      }
    }
    throw new Error('AUDIO_NETWORK');
  }
  clear() {
    this.generation++;
    for (const job of this.jobs.values()) {
      job.controller.abort();
      job.reject(aborted());
    }
    this.jobs.clear();
    this.queue = [];
    this.active = 0;
    this.cache.clear();
    this.sources.clear();
    this.failures.clear();
    this.notify();
  }
}
