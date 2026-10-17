import { useCallback, useEffect, useRef, useState } from 'react';
import { audioPlayer } from '../platform/audio/browser-audio-player';

export type LearningAudio = {
  narration: Record<string, boolean>;
  lessons: Record<
    string,
    { audioId: string; title: string; available: boolean; sourceType: string }
  >;
};

/** Playback failure stays separate from answers and never creates learning records. */
export function useLearningVoice(scope: string | null) {
  const [playingId, setPlayingId] = useState<string | null>(null);
  const [failureId, setFailureId] = useState<string | null>(null);
  const [completed, setCompleted] = useState<{ scope: string | null; ids: ReadonlySet<string> }>(
    () => ({ scope, ids: new Set() }),
  );
  // A previous exercise's playback cannot unlock a new instance of the same question.
  const completedIds = completed.scope === scope ? completed.ids : new Set<string>();
  const [failedIds, setFailedIds] = useState<ReadonlySet<string>>(() => new Set());
  const failedKind = useRef<'private' | 'standard' | 'daily'>('private');
  const active = useRef<AbortController | null>(null);
  const release = useCallback(() => {
    active.current?.abort();
    active.current = null;
  }, []);
  const stop = useCallback(() => {
    release();
    setPlayingId(null);
    setFailureId(null);
  }, [release]);
  const playAsset = useCallback(
    (id: string, kind: 'private' | 'standard' | 'daily') => {
      release();
      if (document.hidden) return;
      const controller = new AbortController();
      active.current = controller;
      setFailureId(null);
      setPlayingId(id);
      // Cancelling a replay does not undo a previously completed listen in this task.
      const playback =
        kind === 'standard'
          ? audioPlayer.play(id, controller.signal)
          : kind === 'daily'
            ? audioPlayer.playDaily(id, controller.signal)
            : audioPlayer.playPrivate(id, controller.signal);
      void playback
        .then(() => {
          if (active.current === controller && !controller.signal.aborted) {
            setCompleted((previous) => ({
              scope,
              ids: new Set(previous.scope === scope ? previous.ids : []).add(id),
            }));
            setFailedIds((previous) => {
              const next = new Set(previous);
              next.delete(id);
              return next;
            });
          }
        })
        .catch((error: unknown) => {
          if (active.current === controller && !controller.signal.aborted) {
            if (!(error instanceof Error && error.name === 'AbortError')) {
              failedKind.current = kind;
              setFailureId(id);
              setFailedIds((previous) => new Set(previous).add(id));
            }
          }
        })
        .finally(() => {
          if (active.current === controller) {
            active.current = null;
            setPlayingId(null);
          }
        });
    },
    [release, scope],
  );
  const play = useCallback((id: string) => playAsset(id, 'private'), [playAsset]);
  const playDaily = useCallback((id: string) => playAsset(id, 'daily'), [playAsset]);
  const playStandard = useCallback((id: string) => playAsset(id, 'standard'), [playAsset]);
  const retry = () => {
    if (failureId) playAsset(failureId, failedKind.current);
  };
  useEffect(() => {
    const onHidden = () => {
      if (document.hidden) stop();
    };
    document.addEventListener('visibilitychange', onHidden);
    return () => {
      document.removeEventListener('visibilitychange', onHidden);
      release();
    };
  }, [release, stop, scope]);
  return {
    playingId,
    failureId,
    completedIds,
    failedIds,
    play,
    playStandard,
    playDaily,
    retry,
    stop,
  };
}

export type LearningVoice = ReturnType<typeof useLearningVoice>;

export function VoiceButton({
  id,
  voice,
  label = '听一听',
  className = '',
  kind = 'private',
}: {
  id: string;
  voice: LearningVoice;
  label?: string;
  className?: string;
  kind?: 'private' | 'standard' | 'daily';
}) {
  const playing = voice.playingId === id;
  const failed = voice.failedIds.has(id);
  return (
    <button
      type="button"
      className={`voice-button ${className}`}
      aria-label={playing ? `停止${label}` : label}
      aria-pressed={playing}
      aria-description={failed ? '这段声音没有播放成功，点这里重试。' : undefined}
      onClick={() =>
        playing
          ? voice.stop()
          : kind === 'standard'
            ? voice.playStandard(id)
            : kind === 'daily'
              ? voice.playDaily(id)
              : voice.play(id)
      }
    >
      <span aria-hidden="true">{playing ? '■' : voice.failedIds.has(id) ? '↻' : '🔊'}</span>
      {playing ? '停止' : label}
    </button>
  );
}

export function VoiceFailure({ voice }: { voice: LearningVoice }) {
  if (!voice.failureId) return null;
  return (
    <div className="voice-failure" role="alert">
      <span>🔊 声音还没有响起来，请点一下重试。仍然没有声音时，请家长检查 Mac 上的学习音频。</span>
      <button className="quiet" onClick={voice.retry}>
        ↻ 重试声音
      </button>
    </div>
  );
}
