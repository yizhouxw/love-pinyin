import type { AudioPlayer } from '../../domain/contracts';
import { learningAssetUrl } from '../guest';
import { ReadingAudioPool } from './reading-audio-pool';

type ActivePlayback = { stop: () => void };
export type PlaybackObserver = {
  onStart?: () => void;
  onTime?: (seconds: number) => void;
  onState?: (state: 'loading' | 'playing') => void;
};

function aborted(): DOMException {
  return new DOMException('Audio playback stopped.', 'AbortError');
}

/** One active playback across same-origin learning media; callers pass asset IDs. */
export class BrowserAudioPlayer implements AudioPlayer {
  private active: ActivePlayback | null = null;
  private privateMedia: HTMLAudioElement | null = null;
  private readingMedia: HTMLAudioElement | null = null;
  private readingPrimed = false;
  readonly readingPool = new ReadingAudioPool();

  prepareReading(sources: { kind: 'voice' | 'daily-audio'; id: string }[]) {
    this.readingPool.prepare(sources.map((value) => learningAssetUrl(value.kind, value.id)));
  }
  prioritizeReading(sources: { kind: 'voice' | 'daily-audio'; id: string }[]) {
    this.readingPool.prioritize(sources.map((value) => learningAssetUrl(value.kind, value.id)));
  }
  releaseReading() {
    this.stop();
    this.readingPool.clear();
    this.readingMedia = null;
    this.readingPrimed = false;
  }

  play(audioId: string, signal?: AbortSignal): Promise<void> {
    return this.playFrom('audio', audioId, signal);
  }

  playDaily(audioId: string, signal?: AbortSignal, observer?: PlaybackObserver): Promise<void> {
    return this.playFrom('daily-audio', audioId, signal, observer);
  }

  /** Private narration and family course recordings share the same playback lifetime. */
  playPrivate(audioId: string, signal?: AbortSignal, observer?: PlaybackObserver): Promise<void> {
    return this.playFrom('voice', audioId, signal, observer);
  }

  /** Native controls keep pause/seek support for long courses while sharing the singleton. */
  registerExternalMedia(media: HTMLMediaElement): () => void {
    const playback: ActivePlayback = { stop: () => media.pause() };
    const onPlay = () => {
      if (document.hidden) {
        media.pause();
        return;
      }
      this.stop();
      this.active = playback;
    };
    const onPause = () => {
      if (this.active === playback) this.active = null;
    };
    media.addEventListener('play', onPlay);
    media.addEventListener('pause', onPause);
    media.addEventListener('ended', onPause);
    return () => {
      media.removeEventListener('play', onPlay);
      media.removeEventListener('pause', onPause);
      media.removeEventListener('ended', onPause);
      media.pause();
      if (this.active === playback) this.active = null;
    };
  }

  private playFrom(
    kind: 'audio' | 'voice' | 'daily-audio',
    audioId: string,
    signal?: AbortSignal,
    observer?: PlaybackObserver,
  ): Promise<void> {
    this.stop();
    if (typeof document !== 'undefined' && document.hidden) return Promise.reject(aborted());
    if (!audioId.trim()) return Promise.reject(new Error('AUDIO_ID_INVALID'));
    if (signal?.aborted) return Promise.reject(aborted());

    const source = learningAssetUrl(kind, audioId);
    if (kind === 'daily-audio' || (kind === 'voice' && audioId.startsWith('daily-')))
      return this.playBufferedReading(source, signal, observer);
    // Reuse the narration element after the child's first tap so iOS can keep its
    // media activation when a subsequent question starts after an API response.
    const audio = kind === 'voice' ? (this.privateMedia ??= new Audio(source)) : new Audio(source);
    if (audio.getAttribute('src') !== source) audio.src = source;
    audio.preload = 'auto';

    return new Promise((resolve, reject) => {
      let settled = false;
      let frame: number | undefined;
      let watchdog: ReturnType<typeof setTimeout> | undefined;
      let lastTime = 0;
      const watchProgress = () => {
        clearTimeout(watchdog);
        watchdog = setTimeout(() => finish(new Error('AUDIO_STALLED')), 15000);
      };
      const onProgress = () => {
        if (audio.currentTime > lastTime) {
          lastTime = audio.currentTime;
          watchProgress();
        }
      };
      const notifyTime = () => {
        if (settled) return;
        observer?.onTime?.(audio.currentTime);
        frame = requestAnimationFrame(notifyTime);
      };
      const onPlaying = () => {
        watchProgress();
        observer?.onStart?.();
        if (observer?.onTime && frame === undefined) notifyTime();
      };
      const finish = (error?: Error) => {
        if (settled) return;
        settled = true;
        clearTimeout(watchdog);
        if (frame !== undefined) cancelAnimationFrame(frame);
        audio.removeEventListener('playing', onPlaying);
        audio.removeEventListener('timeupdate', onProgress);
        audio.removeEventListener('ended', onEnded);
        audio.removeEventListener('error', onError);
        signal?.removeEventListener('abort', onAbort);
        if (this.active === playback) this.active = null;
        audio.pause();
        audio.removeAttribute('src');
        audio.load();
        if (error) reject(error);
        else resolve();
      };
      const onEnded = () => finish();
      const onError = () => finish(new Error('AUDIO_UNAVAILABLE'));
      const onAbort = () => finish(aborted());
      const playback: ActivePlayback = { stop: onAbort };

      this.active = playback;
      audio.addEventListener('ended', onEnded, { once: true });
      audio.addEventListener('playing', onPlaying);
      audio.addEventListener('timeupdate', onProgress);
      audio.addEventListener('error', onError, { once: true });
      signal?.addEventListener('abort', onAbort, { once: true });
      watchdog = setTimeout(() => finish(new Error('AUDIO_TIMEOUT')), 30000);
      try {
        void audio.play().catch(() => finish(new Error('AUDIO_UNAVAILABLE')));
      } catch {
        finish(new Error('AUDIO_UNAVAILABLE'));
      }
    });
  }

  private playBufferedReading(
    source: string,
    signal?: AbortSignal,
    observer?: PlaybackObserver,
  ): Promise<void> {
    const audio = (this.readingMedia ??= new Audio(''));
    audio.preload = 'auto';
    return new Promise((resolve, reject) => {
      let settled = false;
      let url: string | null = null;
      let primeUrl: string | null = null;
      let frame: number | undefined;
      let watchdog: ReturnType<typeof setTimeout> | undefined;
      const controller = new AbortController();
      const finish = (error?: Error) => {
        if (settled) return;
        settled = true;
        controller.abort();
        clearTimeout(watchdog);
        if (frame !== undefined) cancelAnimationFrame(frame);
        audio.removeEventListener('playing', onPlaying);
        audio.removeEventListener('timeupdate', onProgress);
        audio.removeEventListener('waiting', onWaiting);
        audio.removeEventListener('stalled', onWaiting);
        audio.removeEventListener('ended', onEnded);
        audio.removeEventListener('error', onError);
        signal?.removeEventListener('abort', onAbort);
        if (this.active === playback) this.active = null;
        audio.pause();
        audio.removeAttribute('src');
        audio.load();
        audio.removeAttribute('data-learning-source');
        if (url) URL.revokeObjectURL(url);
        if (primeUrl) URL.revokeObjectURL(primeUrl);
        if (error) reject(error);
        else resolve();
      };
      const armWatchdog = () => {
        clearTimeout(watchdog);
        watchdog = setTimeout(() => finish(new Error('AUDIO_STALLED')), 10000);
      };
      const notifyTime = () => {
        if (settled) return;
        observer?.onTime?.(audio.currentTime);
        frame = requestAnimationFrame(notifyTime);
      };
      const onPlaying = () => {
        observer?.onState?.('playing');
        observer?.onStart?.();
        armWatchdog();
        if (observer?.onTime && frame === undefined) notifyTime();
      };
      const onProgress = () => armWatchdog();
      const onWaiting = () => {
        observer?.onState?.('loading');
        armWatchdog();
      };
      const onEnded = () => finish();
      const onError = () =>
        finish(
          new Error(
            audio.error?.code === 3 || audio.error?.code === 4
              ? 'AUDIO_DECODE_FAILED'
              : 'AUDIO_NETWORK',
          ),
        );
      const onAbort = () => finish(aborted());
      const playback: ActivePlayback = { stop: onAbort };
      this.active = playback;
      signal?.addEventListener('abort', onAbort, { once: true });
      observer?.onState?.('loading');
      watchdog = setTimeout(() => finish(new Error('AUDIO_TIMEOUT')), 30000);
      // This is a silent media-activation step, never a lesson sample or completion.
      let activation: Promise<void> = Promise.resolve();
      if (!this.readingPrimed) {
        primeUrl = URL.createObjectURL(silentReadingPrimer());
        audio.src = primeUrl;
        try {
          activation = audio
            .play()
            .then(() => {
              if (settled || this.active !== playback) throw aborted();
              this.readingPrimed = true;
              audio.pause();
            })
            .finally(() => {
              if (primeUrl) URL.revokeObjectURL(primeUrl);
              primeUrl = null;
            });
        } catch (error) {
          URL.revokeObjectURL(primeUrl);
          activation = Promise.reject(error);
        }
      }
      void Promise.all([activation, this.readingPool.get(source, true, controller.signal)])
        .then(([, blob]) => {
          if (settled) return;
          if (document.hidden || signal?.aborted) {
            finish(aborted());
            return;
          }
          url = URL.createObjectURL(blob);
          audio.setAttribute('data-learning-source', source);
          audio.src = url;
          audio.addEventListener('playing', onPlaying);
          audio.addEventListener('timeupdate', onProgress);
          audio.addEventListener('waiting', onWaiting);
          audio.addEventListener('stalled', onWaiting);
          audio.addEventListener('ended', onEnded, { once: true });
          audio.addEventListener('error', onError, { once: true });
          armWatchdog();
          return audio.play();
        })
        .catch((error: unknown) => {
          if (settled) return;
          if (error instanceof Error && error.name === 'NotAllowedError') {
            this.readingPrimed = false;
            finish(new Error('AUDIO_GESTURE_REQUIRED'));
          } else if (error instanceof Error && error.name === 'NotSupportedError') {
            finish(new Error('AUDIO_DECODE_FAILED'));
          } else finish(error instanceof Error ? error : new Error('AUDIO_UNAVAILABLE'));
        });
    });
  }

  stop(): void {
    this.active?.stop();
  }
}

export const audioPlayer = new BrowserAudioPlayer();

/** Twenty milliseconds of zero PCM, used only to unlock this reusable media element. */
function silentReadingPrimer(): Blob {
  const bytes = new Uint8Array(44 + 960);
  const view = new DataView(bytes.buffer);
  const text = (offset: number, value: string) =>
    [...value].forEach((char, i) => view.setUint8(offset + i, char.charCodeAt(0)));
  text(0, 'RIFF');
  view.setUint32(4, bytes.length - 8, true);
  text(8, 'WAVE');
  text(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, 1, true);
  view.setUint32(24, 24000, true);
  view.setUint32(28, 48000, true);
  view.setUint16(32, 2, true);
  view.setUint16(34, 16, true);
  text(36, 'data');
  view.setUint32(40, 960, true);
  return new Blob([bytes], { type: 'audio/wav' });
}
