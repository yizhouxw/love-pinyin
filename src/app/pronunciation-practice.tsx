import practice from '../../content/pronunciation-practice.json';
import { useEffect, useMemo, useRef, useState } from 'react';
import type { PronunciationService, PronunciationTarget } from '../domain/pronunciation';
import {
  coursePronunciationTargets,
  pronunciationSummary,
  type PronunciationAssessment,
  type PronunciationHistory,
} from '../domain/pronunciation-practice';
import {
  createHttpPronunciationService,
  pronunciationHistory,
} from '../platform/audio/pronunciation-http';
import { BrowserReadingRecorder } from '../platform/audio/browser-reading-recorder';
import { recordingWav } from '../platform/audio/recording-wav';
import { audioPlayer } from '../platform/audio/browser-audio-player';
import { isGuest } from '../platform/guest';

const labels = practice.results;

export function PronunciationResults({
  targetId,
  audioUrl,
  service,
  guidanceEnabled = true,
}: {
  targetId: string;
  audioUrl?: string | null;
  service?: PronunciationService;
  guidanceEnabled?: boolean;
}) {
  const { requestId } = useMemo(
    () => ({ targetId, audioUrl, requestId: crypto.randomUUID() }),
    [targetId, audioUrl],
  );
  const http = useRef(createHttpPronunciationService());
  const guidance = useRef(guidanceEnabled);
  useEffect(() => {
    guidance.current = guidanceEnabled;
  }, [guidanceEnabled]);
  const active = useRef<AbortController | null>(null);
  const [result, setResult] = useState<PronunciationAssessment | null>(null);
  const [history, setHistory] = useState<PronunciationHistory>({ items: [], counts: {} });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [historyError, setHistoryError] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    if (service) return;
    const controller = new AbortController();
    void pronunciationHistory(targetId, controller.signal)
      .then((value) => {
        if (!controller.signal.aborted) {
          setHistory(value);
          setHistoryError(false);
        }
      })
      .catch(() => {
        if (!controller.signal.aborted) setHistoryError(true);
      });
    return () => controller.abort();
  }, [targetId, refresh, service]);

  useEffect(() => {
    if (!audioUrl) return;
    const controller = new AbortController();
    active.current = controller;
    void (async () => {
      setBusy(true);
      setError('');
      setResult(null);
      try {
        const wav = await recordingWav(audioUrl, controller.signal);
        const request = {
          requestId,
          targetId,
          audio: wav,
          signal: controller.signal,
        };
        const assessment = service
          ? {
              match: await service.match(request),
              recognition: await service.recognize(request),
              createdAt: new Date().toISOString(),
              saved: false,
            }
          : await http.current.assess(request);
        if (controller.signal.aborted || active.current !== controller) return;
        if (
          [assessment.match, assessment.recognition].some(
            (value) =>
              value.requestId !== request.requestId ||
              value.targetId !== targetId ||
              value.contractVersion !== 1,
          )
        )
          throw new Error('INVALID_RESPONSE');
        setResult(assessment);
        if (guidance.current) {
          const status =
            assessment.match.status === 'retry' ? 'different' : assessment.match.status;
          void audioPlayer
            .playPrivate(`recognition-${status}`, controller.signal)
            .catch(() => undefined);
        }
        if (!service && isGuest() && assessment.match.evidence === 'acoustic') {
          setHistory((previous) =>
            previous.items.some((item) => item.match.requestId === assessment.match.requestId)
              ? previous
              : {
                  items: [assessment, ...previous.items].slice(0, 20),
                  counts: {
                    ...previous.counts,
                    [assessment.match.status]: (previous.counts[assessment.match.status] ?? 0) + 1,
                  },
                },
          );
        } else if (assessment.saved) setRefresh((value) => value + 1);
      } catch (error) {
        if (!controller.signal.aborted)
          setError(
            error instanceof Error && error.message === 'READING_TOO_LONG'
              ? '这段超过三十秒，请分条录音。不算读错。'
              : '暂时无法识别或保存，请重试。不算读错。',
          );
      } finally {
        if (!controller.signal.aborted) setBusy(false);
      }
    })();
    const hide = () => {
      if (document.hidden) {
        controller.abort();
        setBusy(false);
        setResult(null);
      }
    };
    document.addEventListener('visibilitychange', hide);
    return () => {
      controller.abort();
      document.removeEventListener('visibilitychange', hide);
    };
  }, [audioUrl, targetId, requestId, attempt, service]);

  const summary = pronunciationSummary(history);
  return (
    <section className="daily-recognition pronunciation-results" aria-label="拼读准确情况">
      <h3>拼读识别与记录</h3>
      <p>
        专用声音识别服务尚未启用时会提示不可用。仅有可靠声音证据才记录相符或不同；不计入选择题掌握度。
      </p>
      {audioUrl && busy && (
        <p role="status">
          正在识别拼读…{' '}
          <button
            onClick={() => {
              active.current?.abort();
              setBusy(false);
              setError('已取消，可以重新识别。不算读错。');
            }}
          >
            取消识别
          </button>
        </p>
      )}
      {audioUrl && !busy && (
        <button className="quiet" onClick={() => setAttempt((value) => value + 1)}>
          重新识别拼读
        </button>
      )}
      {audioUrl && error && <p role="alert">{error}</p>}
      {audioUrl && result && (
        <div role="status">
          {result.match.evidence === 'mock' && <strong>开发模拟 · 不是真实识别，不保存成绩</strong>}
          <p>{labels[result.match.status]}</p>
          <button
            className="quiet"
            onClick={() => {
              const status = result.match.status === 'retry' ? 'different' : result.match.status;
              void audioPlayer
                .playPrivate(`recognition-${status}`, active.current?.signal)
                .catch(() => setError('结果声音暂时无法播放，请重试。'));
            }}
          >
            🔊 听拼读识别结果
          </button>
          {result.recognition.status === 'recognized' && (
            <p>实际识别拼音：{result.recognition.recognizedPinyin}</p>
          )}
          <p>{result.match.toneAssessed ? '本次包含声调判断' : '本次未判断实际声调'}</p>
          <small>
            {result.saved
              ? '摘要已保存到家庭 Mac；录音不保存。'
              : result.match.evidence === 'acoustic' && isGuest()
                ? '访客记录仅保留本次页面。'
                : '本次没有保存真实识别成绩。'}
          </small>
        </div>
      )}
      {!service && (
        <details>
          <summary>查看本条拼读记录</summary>
          {historyError ? (
            <p role="alert">
              记录暂时无法读取。
              <button onClick={() => setRefresh((value) => value + 1)}>重试读取</button>
            </p>
          ) : (
            <>
              <p>
                有效判断 {summary.assessed} 次，相符 {summary.matched} 次；未判定{' '}
                {summary.undecided} 次。
              </p>
              {history.items.length === 0 && <p>暂无真实声音识别记录。</p>}
              <ul>
                {history.items.map((item) => (
                  <li key={item.match.requestId}>
                    {new Date(item.createdAt).toLocaleString('zh-CN')} · {labels[item.match.status]}
                    {item.recognition.recognizedPinyin
                      ? ` · ${item.recognition.recognizedPinyin}`
                      : ''}{' '}
                    · {item.match.toneAssessed ? '含声调判断' : '未判声调'}
                  </li>
                ))}
              </ul>
            </>
          )}
        </details>
      )}
    </section>
  );
}

function RecordedPractice({
  target,
  audioId,
  service,
  guidanceEnabled,
}: {
  target: PronunciationTarget;
  audioId: string;
  guidanceEnabled: boolean;
  service?: PronunciationService;
}) {
  const recorder = useRef(new BrowserReadingRecorder());
  const active = useRef<AbortController | null>(null);
  const [phase, setPhase] = useState<'idle' | 'starting' | 'recording' | 'stopping'>('idle');
  const [url, setUrl] = useState<string | null>(null);
  const [error, setError] = useState('');
  const replay = useRef<HTMLAudioElement | null>(null);
  const [open, setOpen] = useState(true);
  function clear() {
    active.current?.abort();
    recorder.current.discard();
    replay.current?.pause();
    setUrl(null);
    setPhase('idle');
  }
  useEffect(() => {
    const capture = recorder.current;
    const hidden = () => {
      if (document.hidden) {
        active.current?.abort();
        capture.discard();
        setUrl(null);
        setPhase('idle');
      }
    };
    document.addEventListener('visibilitychange', hidden);
    return () => {
      document.removeEventListener('visibilitychange', hidden);
      active.current?.abort();
      capture.discard();
      audioPlayer.stop();
    };
  }, []);
  useEffect(() => {
    if (replay.current) return audioPlayer.registerExternalMedia(replay.current);
  }, [url]);
  async function record() {
    clear();
    setError('');
    setPhase('starting');
    audioPlayer.stop();
    const controller = new AbortController();
    active.current = controller;
    try {
      // Existing licensed Chinese instruction; a child need not read the controls first.
      if (guidanceEnabled) await audioPlayer.playPrivate('daily-ui-record', controller.signal);
      if (controller.signal.aborted) return;
      await recorder.current.start(
        (value) => {
          setUrl(value);
          setPhase('idle');
        },
        () => {
          setPhase('idle');
          setError('这次没有录好，请再试一次。');
        },
      );
      if (!controller.signal.aborted) setPhase('recording');
    } catch {
      if (!controller.signal.aborted) {
        setPhase('idle');
        setError(
          '请允许麦克风，使用本机地址或受信任 HTTPS。也可以直接听音跟读；若说明声音失败，请重试。',
        );
      }
    }
  }
  return (
    <details
      className="pronunciation-capture"
      open={open}
      onToggle={(event) => {
        setOpen(event.currentTarget.open);
        if (!event.currentTarget.open) clear();
      }}
    >
      <summary>🎙 听一听，读一读（可选）</summary>
      <p className="pronunciation-target">{target.pinyin}</p>
      <button
        className="quiet"
        disabled={phase !== 'idle'}
        onClick={() => {
          replay.current?.pause();
          void audioPlayer.play(audioId).catch(() => setError('示范声音暂不可用，请重试。'));
        }}
      >
        ♫ 听示范
      </button>
      {phase === 'recording' ? (
        <button
          onClick={() => {
            setPhase('stopping');
            recorder.current.stop();
          }}
        >
          ■ 停止录音并识别
        </button>
      ) : (
        <button disabled={phase !== 'idle'} onClick={() => void record()}>
          🎙 {url ? '重新录音' : '录下我的跟读'}
        </button>
      )}
      <button className="quiet" onClick={clear}>
        取消并清除录音
      </button>
      <p>
        录音只在内存处理，每段识别最多三十秒，录音两分钟安全停止。退出、换条或后台清除录音，家庭仅保存真实识别摘要。
      </p>
      {error && <p role="alert">{error}</p>}
      {url && <audio ref={replay} src={url} controls aria-label="回放课程跟读" />}
      {open && (
        <PronunciationResults
          targetId={target.id}
          audioUrl={url}
          service={service}
          guidanceEnabled={guidanceEnabled}
        />
      )}
    </details>
  );
}

export function CoursePronunciationPractice({
  lessonId,
  guidanceEnabled,
}: {
  lessonId: string;
  guidanceEnabled: boolean;
}) {
  const targets = coursePronunciationTargets.filter((target) => target.lessonId === lessonId);
  const [index, setIndex] = useState(0);
  const target = targets[index];
  if (!target) return null;
  return (
    <section className="lesson-pronunciation" aria-label="课程拼读跟读">
      <h3>课程拼读跟读</h3>
      <nav aria-label="选择跟读目标">
        {targets.map((item, position) => (
          <button
            className="quiet"
            key={item.id}
            aria-pressed={position === index}
            onClick={() => setIndex(position)}
          >
            {item.pinyin}
          </button>
        ))}
      </nav>
      <RecordedPractice
        key={target.id}
        target={target}
        audioId={target.audioId}
        guidanceEnabled={guidanceEnabled}
      />
    </section>
  );
}
