import { useEffect, useRef, useState } from 'react';
import { audioPlayer } from '../platform/audio/browser-audio-player';
import { iosOperation } from '../platform/ios-app';

type PlaybackState = { playing: boolean; position: number; duration: number };
let nextPlaybackId = 0;

export function IOSLessonAudio({ audioId }: { audioId: string }) {
  const [id] = useState(() => ++nextPlaybackId);
  const [state, setState] = useState<PlaybackState>({ playing: false, position: 0, duration: 0 });
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const release = useRef<(() => void) | null>(null);
  const mounted = useRef(false);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      release.current?.();
      void iosOperation('pauseLesson', { id }).catch(() => undefined);
    };
  }, [id]);

  useEffect(() => {
    if (!state.playing) return;
    let active = true;
    let pending = false;
    const timer = setInterval(() => {
      if (pending) return;
      pending = true;
      iosOperation<PlaybackState>('lessonState', { id })
        .then(
          (result) => {
            if (active) setState(result);
          },
          () => {
            if (active) {
              setFailed(true);
              setState((value) => ({ ...value, playing: false }));
            }
          },
        )
        .finally(() => {
          pending = false;
        });
    }, 300);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [id, state.playing]);

  async function control(operation: string, fields: Record<string, unknown> = {}) {
    setBusy(true);
    setFailed(false);
    try {
      const result = await iosOperation<PlaybackState>(operation, { id, ...fields });
      if (mounted.current) setState(result);
    } catch {
      if (mounted.current) setFailed(true);
    } finally {
      if (mounted.current) setBusy(false);
    }
  }

  return (
    <>
      <button
        className="voice-button"
        disabled={busy}
        aria-pressed={state.playing}
        onClick={() => {
          if (state.playing) {
            release.current?.();
            void control('pauseLesson');
          } else {
            release.current?.();
            release.current = audioPlayer.claimAudio(() => {
              setState((value) => ({ ...value, playing: false }));
              void iosOperation('pauseLesson', { id }).catch(() => undefined);
            });
            void control('playLesson', { audioId });
          }
        }}
      >
        {state.playing ? 'Ⅱ 暂停课程录音' : '▶ 播放课程录音'}
      </button>
      {state.duration > 0 && (
        <input
          type="range"
          aria-label="课程录音播放进度"
          aria-valuetext={`第 ${Math.floor(state.position)} 秒，共 ${Math.ceil(state.duration)} 秒`}
          min={0}
          max={state.duration}
          step={0.1}
          value={state.position}
          disabled={busy}
          onChange={(event) =>
            void control('seekLesson', { seconds: event.currentTarget.valueAsNumber })
          }
        />
      )}
      {failed && <p role="alert">课程录音未能播放，请重试。</p>}
    </>
  );
}
