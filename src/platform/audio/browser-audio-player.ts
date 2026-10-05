import type { AudioPlayer } from '../../domain/contracts';

type ActivePlayback = { stop: () => void };

function aborted(): DOMException {
  return new DOMException('Audio playback stopped.', 'AbortError');
}

/** One same-origin audio element shared by the application; it never accepts URLs. */
export class BrowserAudioPlayer implements AudioPlayer {
  private active: ActivePlayback | null = null;
  private privateMedia: HTMLAudioElement | null = null;

  play(audioId: string, signal?: AbortSignal): Promise<void> {
    return this.playFrom('audio', audioId, signal);
  }

  /** Private narration and family course recordings share the same playback lifetime. */
  playPrivate(audioId: string, signal?: AbortSignal): Promise<void> {
    return this.playFrom('voice', audioId, signal);
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

  private playFrom(kind: 'audio' | 'voice', audioId: string, signal?: AbortSignal): Promise<void> {
    this.stop();
    if (typeof document !== 'undefined' && document.hidden) return Promise.reject(aborted());
    if (!audioId.trim()) return Promise.reject(new Error('AUDIO_ID_INVALID'));
    if (signal?.aborted) return Promise.reject(aborted());

    const source = `/api/v1/${kind}/${encodeURIComponent(audioId)}`;
    // Reuse the narration element after the child's first tap so iOS can keep its
    // media activation when a subsequent question starts after an API response.
    const audio = kind === 'voice' ? (this.privateMedia ??= new Audio(source)) : new Audio(source);
    if (audio.src !== source) audio.src = source;
    audio.preload = 'auto';

    return new Promise((resolve, reject) => {
      let settled = false;
      const finish = (error?: Error) => {
        if (settled) return;
        settled = true;
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
      audio.addEventListener('error', onError, { once: true });
      signal?.addEventListener('abort', onAbort, { once: true });
      try {
        void audio.play().catch(() => finish(new Error('AUDIO_UNAVAILABLE')));
      } catch {
        finish(new Error('AUDIO_UNAVAILABLE'));
      }
    });
  }

  stop(): void {
    this.active?.stop();
  }
}

export const audioPlayer = new BrowserAudioPlayer();
