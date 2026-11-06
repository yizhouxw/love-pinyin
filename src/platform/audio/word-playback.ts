import { waitForPlaybackGap } from './playback-gap';

type State = {
  playingId: string | null;
  failureId: string | null;
  continuous: boolean;
  index: number;
  total: number;
  waiting: boolean;
};
const idle: State = {
  playingId: null,
  failureId: null,
  continuous: false,
  index: 0,
  total: 0,
  waiting: false,
};
/** A finite, cancellable queue. A retry resumes the failed word and remaining words. */
export class WordPlayback {
  private state: State = idle;
  private listeners = new Set<() => void>();
  private controller: AbortController | null = null;
  private retryPlan: { ids: string[]; index: number; gap: number; continuous: boolean } | null =
    null;
  constructor(private readonly playAudio: (id: string, signal: AbortSignal) => Promise<void>) {}
  snapshot = () => this.state;
  subscribe = (listener: () => void) => {
    this.listeners.add(listener);
    return () => {
      this.listeners.delete(listener);
    };
  };
  private update(state: State) {
    this.state = state;
    this.listeners.forEach((listener) => listener());
  }
  stop = () => {
    this.controller?.abort();
    this.controller = null;
    this.retryPlan = null;
    this.update(idle);
  };
  play = (id: string) => this.start([id], 0, 0, false);
  playSequence = (ids: string[], gap = 0, continuous = false) =>
    this.start(ids, 0, gap, continuous);
  retry = () => {
    const plan = this.retryPlan;
    if (plan) this.start(plan.ids, plan.index, plan.gap, plan.continuous);
  };
  private start(ids: string[], from: number, gap: number, continuous: boolean) {
    this.stop();
    if (!ids.length) return;
    const controller = new AbortController();
    this.controller = controller;
    void (async () => {
      for (let index = from; index < ids.length; index++) {
        if (controller.signal.aborted) return;
        const id = ids[index]!;
        this.update({ ...idle, playingId: id, continuous, index, total: ids.length });
        try {
          await this.playAudio(id, controller.signal);
          if (this.controller !== controller || controller.signal.aborted) return;
          if (index < ids.length - 1 && gap > 0) {
            this.update({ ...this.state, waiting: true });
            await waitForPlaybackGap(gap, controller.signal);
          }
        } catch {
          if (this.controller !== controller || controller.signal.aborted) return;
          this.retryPlan = { ids, index, gap, continuous };
          this.controller = null;
          this.update({ ...idle, failureId: id, index, total: ids.length });
          return;
        }
      }
      if (this.controller === controller) {
        this.controller = null;
        this.update(idle);
      }
    })();
  }
}
