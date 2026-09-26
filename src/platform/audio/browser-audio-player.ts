import type { AudioPlayer } from '../../domain/contracts';

type ActivePlayback = { stop: () => void };

function aborted(): DOMException {
  return new DOMException('Audio playback stopped.', 'AbortError');
}

/** One same-origin audio element shared by the application; it never accepts URLs. */
export class BrowserAudioPlayer implements AudioPlayer {
  private active: ActivePlayback | null = null;

  play(audioId: string, signal?: AbortSignal): Promise<void> {
    this.stop();
    if (!audioId.trim()) return Promise.reject(new Error('AUDIO_ID_INVALID'));
    if (signal?.aborted) return Promise.reject(aborted());

    const source = `/api/v1/audio/${encodeURIComponent(audioId)}`;
    const audio = new Audio(source);
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
