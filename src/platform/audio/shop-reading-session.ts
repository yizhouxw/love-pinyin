import type { PronunciationService, PronunciationTarget } from '../../domain/pronunciation';
import { shopOutcome, type ShopOutcome } from '../../domain/pinyin-shop';
import type { ShopCapture } from './browser-shop-recorder';

export type ShopReadingOutcome = Exclude<ShopOutcome, 'stale'> | 'timeout' | 'microphone';
export type ShopReadingCallbacks = {
  phase: (phase: 'starting' | 'listening') => void;
  outcome: (outcome: ShopReadingOutcome) => void;
};
/** One active commodity, one serial MATCH-10 request, one five-second capture/inference budget. */
export class ShopReadingSession {
  private epoch = 0;
  private request: AbortController | null = null;
  private deadline: ReturnType<typeof setTimeout> | null = null;
  private poll: ReturnType<typeof setTimeout> | null = null;
  constructor(
    private readonly capture: ShopCapture,
    private readonly service: PronunciationService,
    private readonly mock: boolean,
    private readonly timing: {
      recognitionTimeoutMs: number;
      minimumAudioMs: number;
      pollIntervalMs: number;
    },
  ) {}
  cancel(): void {
    this.epoch += 1;
    this.request?.abort();
    this.request = null;
    if (this.deadline) clearTimeout(this.deadline);
    if (this.poll) clearTimeout(this.poll);
    this.deadline = null;
    this.poll = null;
    this.capture.discard();
  }
  async start(target: PronunciationTarget, callbacks: ShopReadingCallbacks): Promise<void> {
    this.cancel();
    const generation = this.epoch;
    callbacks.phase('starting');
    const finish = (outcome: ShopReadingOutcome) => {
      if (this.epoch !== generation) return;
      this.cancel();
      callbacks.outcome(outcome);
    };
    try {
      await this.capture.start();
      if (generation !== this.epoch) return;
      const until = performance.now() + this.timing.recognitionTimeoutMs;
      this.deadline = setTimeout(() => finish('timeout'), this.timing.recognitionTimeoutMs);
      callbacks.phase('listening');
      const tick = async () => {
        if (generation !== this.epoch) return;
        if (performance.now() >= until) {
          finish('timeout');
          return;
        }
        const audio = this.capture.snapshot();
        if (audio) {
          const controller = new AbortController();
          this.request = controller;
          const requestId = crypto.randomUUID();
          try {
            const result = await this.service.match({
              requestId,
              targetId: target.id,
              audio,
              signal: controller.signal,
            });
            if (generation !== this.epoch || controller.signal.aborted) return;
            if (performance.now() >= until) {
              finish('timeout');
              return;
            }
            const outcome = shopOutcome(result, requestId, target.id, this.mock);
            if (outcome !== 'uncertain') {
              finish(outcome === 'stale' ? 'unavailable' : outcome);
              return;
            }
          } catch {
            if (generation !== this.epoch) return;
            finish('unavailable');
            return;
          }
          if (this.request === controller) this.request = null;
        }
        if (generation === this.epoch)
          this.poll = setTimeout(() => {
            void tick();
          }, this.timing.pollIntervalMs);
      };
      this.poll = setTimeout(() => {
        void tick();
      }, this.timing.minimumAudioMs);
    } catch {
      if (generation === this.epoch) finish('microphone');
    }
  }
}
