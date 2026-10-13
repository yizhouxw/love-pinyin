import { useCallback, useEffect, useRef, useState } from 'react';
import type {
  DailyDay,
  DailyItem,
  DailyReading,
  DailySection,
  ReadingMark,
} from '../domain/daily-reading';
import { sectionSummary } from '../domain/daily-reading';
import { audioPlayer } from '../platform/audio/browser-audio-player';
import { BrowserReadingRecorder } from '../platform/audio/browser-reading-recorder';
import { isGuest } from '../platform/guest';
import { recognizeReading, type RecognitionResult } from '../platform/audio/reading-recognition';
import { GuidanceSwitch } from './guidance-switch';
import recognitionContent from '../../content/reading-recognition.json';

async function readDaily(): Promise<DailyReading> {
  const response = await fetch(`/api/v1/${isGuest() ? 'guest/' : ''}daily-reading`);
  if (!response.ok) throw new Error('DAILY_UNAVAILABLE');
  return response.json() as Promise<DailyReading>;
}

export function DailyReadingPage({
  onBack,
  guidanceEnabled,
  onGuidanceChange,
}: {
  onBack: () => void;
  guidanceEnabled: boolean;
  onGuidanceChange: (enabled: boolean) => void;
}) {
  const [data, setData] = useState<DailyReading | null>(null);
  const [error, setError] = useState(false);
  const [dayId, setDayId] = useState('day-01');
  const [sectionId, setSectionId] = useState<string | null>(null);
  const [marks, setMarks] = useState<Record<string, ReadingMark>>({});
  const load = useCallback(() => {
    setError(false);
    void readDaily()
      .then(setData)
      .catch(() => setError(true));
  }, []);
  useEffect(() => {
    let active = true;
    void readDaily()
      .then((value) => {
        if (active) setData(value);
      })
      .catch(() => {
        if (active) setError(true);
      });
    return () => {
      active = false;
      audioPlayer.stop();
    };
  }, []);
  const day = data?.days.find((value) => value.id === dayId);
  const section = day?.sections.find((value) => value.id === sectionId);
  return (
    <section className="daily-page" aria-label="天天练拼音">
      <button className="quiet" onClick={onBack}>
        ← 返回小岛
      </button>
      <div className="daily-heading">
        <div>
          <p className="eyebrow">学校练习 · 每天读一点</p>
          <h1>天天练拼音</h1>
          <p>先听一遍，再自己读。每一步都可以慢慢来。</p>
        </div>
        <span className="daily-emblem" aria-hidden="true">
          ā
        </span>
      </div>
      {!section && <GuidanceSwitch enabled={guidanceEnabled} onChange={onGuidanceChange} />}
      <p className="daily-privacy">
        停止录音后，电脑自动识别并匹配音节。录音只发送家庭
        Mac，在内存中处理，不保存。识别匹配不判四声准确度。本次练习标记退出后清除。
      </p>
      {error && (
        <div role="alert">
          暂时连不上每日练习。请检查家庭 Mac。<button onClick={load}>重新连接</button>
        </div>
      )}
      {!data && !error && <p role="status">正在读取每日练习…</p>}
      {data && day && (
        <>
          <nav className="daily-days" aria-label="选择每日练习">
            {data.days.map((value) => (
              <button
                key={value.id}
                className="quiet"
                aria-pressed={dayId === value.id}
                onClick={() => {
                  audioPlayer.stop();
                  setDayId(value.id);
                  setSectionId(null);
                }}
              >
                第 {value.number} 份
              </button>
            ))}
          </nav>
          <div className="daily-section-heading">
            <h2>
              第 {day.number} 份 · {day.title}
            </h2>
            <small>源 PDF 第 {day.sourcePage} 页</small>
          </div>
          <nav className="daily-sections" aria-label="选择练习小节">
            {day.sections.map((value) => {
              const summary = sectionSummary(value, marks);
              return (
                <button
                  key={value.id}
                  className="quiet"
                  aria-pressed={sectionId === value.id}
                  onClick={() => {
                    audioPlayer.stop();
                    setSectionId(value.id);
                  }}
                >
                  <strong>{value.title}</strong>
                  <small>
                    练过 {summary.practiced} / {summary.total} 条
                  </small>
                </button>
              );
            })}
          </nav>
          {section ? (
            <ReadingSession
              key={section.id}
              day={day}
              guidanceEnabled={guidanceEnabled}
              onGuidanceChange={onGuidanceChange}
              section={section}
              marks={marks}
              onMark={(id, mark) => setMarks((previous) => ({ ...previous, [id]: mark }))}
            />
          ) : (
            <div className="daily-preview">
              <p>选择上面一个小节，点“开始跟读”。</p>
              <button onClick={() => setSectionId(day.sections[0]?.id ?? null)}>
                开始第 {day.number} 份跟读
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function ReadingSession({
  day,
  guidanceEnabled,
  onGuidanceChange,
  section,
  marks,
  onMark,
}: {
  day: DailyDay;
  guidanceEnabled: boolean;
  onGuidanceChange: (enabled: boolean) => void;
  section: DailySection;
  marks: Record<string, ReadingMark>;
  onMark: (id: string, mark: ReadingMark) => void;
}) {
  const [index, setIndex] = useState(0);
  const [phase, setPhase] = useState<'ready' | 'playing' | 'follow' | 'finished'>('ready');
  const [highlight, setHighlight] = useState(-1);
  const [failure, setFailure] = useState('');
  const [recording, setRecording] = useState<'idle' | 'requesting' | 'recording' | 'stopping'>(
    'idle',
  );
  const [recordError, setRecordError] = useState('');
  const [recordUrl, setRecordUrl] = useState<string | null>(null);
  const [adultOpen, setAdultOpen] = useState(false);
  const [recognizing, setRecognizing] = useState(false);
  const [recognition, setRecognition] = useState<RecognitionResult | null>(null);
  const controller = useRef<AbortController | null>(null);
  const recorder = useRef(new BrowserReadingRecorder());
  const replay = useRef<HTMLAudioElement | null>(null);
  const item = section.items[index]!;
  const previousGuidance = useRef(guidanceEnabled);
  const guidance = useRef(guidanceEnabled);
  guidance.current = guidanceEnabled;
  const stop = useCallback(() => {
    controller.current?.abort();
    controller.current = null;
    audioPlayer.stop();
    setHighlight(-1);
    setPhase('ready');
    setRecognizing(false);
  }, []);
  useEffect(() => {
    if (previousGuidance.current !== guidanceEnabled && !guidanceEnabled) {
      if (phase === 'playing' || (phase === 'finished' && controller.current)) stop();
      else audioPlayer.stop();
    }
    previousGuidance.current = guidanceEnabled;
  }, [guidanceEnabled, phase, stop]);
  const clearCapture = useCallback(() => {
    controller.current?.abort();
    controller.current = null;
    audioPlayer.stop();
    setRecognition(null);
    setRecognizing(false);
    replay.current?.pause();
    recorder.current.discard();
    setRecordUrl(null);
    setRecording('idle');
    setRecordError('');
  }, []);
  useEffect(() => {
    const capture = recorder.current;
    const onHidden = () => {
      if (document.hidden) {
        stop();
        clearCapture();
      }
    };
    document.addEventListener('visibilitychange', onHidden);
    return () => {
      document.removeEventListener('visibilitychange', onHidden);
      controller.current?.abort();
      audioPlayer.stop();
      capture.discard();
    };
  }, [stop, clearCapture]);
  useEffect(() => {
    const media = replay.current;
    if (!media || !recordUrl) return;
    return audioPlayer.registerExternalMedia(media);
  }, [recordUrl]);

  const playPrivate = (id: string, signal: AbortSignal) => audioPlayer.playPrivate(id, signal);
  async function demo(target: DailyItem, signal: AbortSignal) {
    if (!target.narrationId && (target.missingSyllables.length || !target.audioIds.length))
      throw new Error('NOT_PREPARED');
    if (target.narrationId) {
      setHighlight(-1);
      await playPrivate(target.narrationId, signal);
    } else {
      for (const [position, id] of target.audioIds.entries()) {
        setHighlight(position);
        await audioPlayer.playDaily(id, signal);
      }
    }
    setHighlight(-1);
  }
  async function play(all = false, startIndex = index) {
    stop();
    clearCapture();
    setFailure('');
    const active = new AbortController();
    controller.current = active;
    setPhase('playing');
    try {
      if (guidance.current) await playPrivate(`daily-instruction-${section.id}`, active.signal);
      if (all) {
        for (let cursor = startIndex; cursor < section.items.length; cursor += 1) {
          const target = section.items[cursor]!;
          setIndex(cursor);
          await demo(target, active.signal);
        }
        setPhase('finished');
        if (guidance.current) await playPrivate('daily-ui-done', active.signal);
      } else {
        await demo(section.items[startIndex]!, active.signal);
        if (guidance.current) await playPrivate('daily-ui-follow', active.signal);
        setPhase('follow');
      }
    } catch {
      if (!active.signal.aborted) {
        setFailure('示范声音还没响起来。可以重试；仍然没有声音，请家长检查 Mac 上的每日练习音频。');
        setPhase('ready');
      }
    }
    if (controller.current === active) controller.current = null;
  }
  function select(cursor: number) {
    stop();
    clearCapture();
    setFailure('');
    setAdultOpen(false);
    setIndex(cursor);
  }
  function next(mark: boolean) {
    if (mark && !marks[item.id]) onMark(item.id, 'practiced');
    if (index + 1 < section.items.length) select(index + 1);
    else {
      stop();
      clearCapture();
      setPhase('finished');
    }
  }
  async function record() {
    stop();
    clearCapture();
    setRecording('requesting');
    let instructionHeard = false;
    const active = new AbortController();
    controller.current = active;
    try {
      if (guidance.current) {
        try {
          await playPrivate('daily-ui-record', active.signal);
        } catch (error) {
          if (guidance.current || active.signal.aborted) throw error;
        }
      }
      instructionHeard = true;
      if (active.signal.aborted) return;
      await recorder.current.start(
        (url) => {
          setRecordUrl(url);
          setRecording('idle');
          void judge(url);
        },
        () => {
          setRecording('idle');
          setRecordError('这次没有录好，请重试。也可以直接跟读。');
        },
      );
      setRecording('recording');
    } catch (error) {
      if (!(error instanceof Error && error.name === 'AbortError') && !active.signal.aborted) {
        setRecording('idle');
        if (instructionHeard) {
          setRecordError(
            '麦克风没有开启。请允许麦克风权限，并使用本机地址或受信任 HTTPS。你仍可以直接跟读。',
          );
        } else {
          setFailure('录音说明没有播放成功，请重听示范后再点录音。');
        }
      }
    }
  }
  async function judge(url: string) {
    stop();
    setRecognition(null);
    setRecognizing(true);
    const active = new AbortController();
    controller.current = active;
    try {
      const result = await recognizeReading(item.id, url, active.signal);
      if (active.signal.aborted || controller.current !== active) return;
      setRecognition(result);
      setRecognizing(false);
      if (guidance.current)
        await playPrivate(`recognition-${result.status}`, active.signal).catch(() => undefined);
    } catch (error) {
      if (active.signal.aborted || controller.current !== active) return;
      setRecognizing(false);
      setRecognition({
        status:
          error instanceof Error && error.message === 'READING_TOO_LONG'
            ? 'uncertain'
            : 'unavailable',
        reason: error instanceof Error ? error.message : 'UNAVAILABLE',
        mode: 'asr-syllable-match',
        toneAssessed: false,
      });
    }
    if (controller.current === active) controller.current = null;
  }
  const summary = sectionSummary(section, marks);
  return (
    <div className="daily-workspace">
      <section className="daily-reader" aria-label="当前跟读内容">
        <div className="daily-reader-top">
          <span>{section.title}</span>
          <strong>
            第 {index + 1} / {section.items.length} 条
          </strong>
        </div>
        <GuidanceSwitch enabled={guidanceEnabled} onChange={onGuidanceChange} />
        <p>{section.instruction}</p>
        <button
          className="quiet daily-target"
          aria-label={item.display}
          disabled={recording !== 'idle'}
          onClick={() => void play()}
        >
          {item.syllables.map((syllable, position) => (
            <span key={position} className={highlight === position ? 'daily-highlight' : ''}>
              {syllable}
            </span>
          ))}
        </button>
        {item.original !== item.display && <p className="daily-original">原稿：{item.original}</p>}
        <p className="daily-source-kind">
          {item.narrationId ? '中文词句朗读 · 本机音色' : '拼音标准音 · 逐音节示范'}
        </p>
        {item.audioNotes.length > 0 && (
          <p className="daily-audio-note">{item.audioNotes.join('；')}</p>
        )}
        <p role="status" aria-live="polite">
          {recording === 'requesting'
            ? '正在准备录音，请允许麦克风…'
            : recording === 'recording'
              ? '正在录音，读完点停止。'
              : recording === 'stopping'
                ? '正在结束录音…'
                : phase === 'playing'
                  ? '仔细听一听…'
                  : phase === 'follow'
                    ? '轮到你读啦，读完点下一条。'
                    : phase === 'finished'
                      ? '这一节结束啦，可以休息，也可以再读一遍。'
                      : '点开始跟读，先听示范。'}
        </p>
        {failure && (
          <div className="voice-failure" role="alert">
            {failure}
            <button onClick={() => void play()}>重试示范</button>
          </div>
        )}
        <div className="daily-actions">
          {phase === 'playing' ? (
            <button onClick={stop}>■ 停止示范</button>
          ) : (
            <button disabled={recording !== 'idle'} onClick={() => void play()}>
              {phase === 'ready' ? '🔊 开始跟读' : '🔊 再听示范'}
            </button>
          )}
          <button
            className="quiet"
            disabled={recording !== 'idle' || phase === 'playing'}
            onClick={() => void play(true)}
          >
            ▶ 连播本节
          </button>
          {recording === 'recording' ? (
            <button
              onClick={() => {
                setRecording('stopping');
                recorder.current.stop();
              }}
            >
              ■ 停止录音
            </button>
          ) : (
            <button
              className="quiet"
              disabled={recording !== 'idle' || phase === 'playing'}
              onClick={() => void record()}
            >
              🎙 {recordUrl ? '重新录音' : '录下我的跟读'}
            </button>
          )}
        </div>
        <p className="daily-privacy">
          也可以不录音，直接跟读。停止录音后自动判定；识别每次最多三十秒，录音两分钟自动停止，没有作答倒计时。
        </p>
        {recordError && <p role="alert">{recordError}</p>}
        {recordUrl && (
          <div className="daily-recording">
            <strong>我的跟读 · 听回放比较</strong>
            <audio ref={replay} src={recordUrl} controls aria-label="回放我的跟读" />
            <button className="quiet" onClick={clearCapture}>
              清除这段录音
            </button>
            <p>录音完成不代表识别匹配。电脑仅核对识别出的音节，不判四声准确度。</p>
            <button className="quiet" disabled={recognizing} onClick={() => void judge(recordUrl)}>
              重新识别这段跟读
            </button>
            {recognizing && <p role="status">电脑正在识别你的跟读…</p>}
            {recognition && (
              <div
                className={`daily-recognition daily-recognition-${recognition.status}`}
                role="status"
              >
                <strong>{recognitionContent.ui[recognition.status]}</strong>
                {recognition.transcript && <p>识别文字：{recognition.transcript}</p>}
                {recognition.recognizedPinyin && (
                  <p>识别文字的拼音：{recognition.recognizedPinyin}</p>
                )}
                {recognition.reason === 'READING_TOO_LONG' && (
                  <p>这段超过三十秒，请分条录音再试。</p>
                )}
                <small>仅识别匹配，不是发音分数；字典标调不代表录音的实际声调。</small>
              </div>
            )}
          </div>
        )}
        <div className="daily-next">
          <button className="quiet" disabled={index === 0} onClick={() => select(index - 1)}>
            ← 上一条
          </button>
          <button onClick={() => next(true)}>
            读过了，{index + 1 === section.items.length ? '完成本节' : '下一条 →'}
          </button>
          <button className="quiet" onClick={() => next(false)}>
            先跳过
          </button>
        </div>
        <details
          open={adultOpen}
          onToggle={(event) => setAdultOpen(event.currentTarget.open)}
          className="daily-parent"
        >
          <summary>家长帮助判断</summary>
          <p>仅记录本次页面里的家长观察，不是自动判音，不计入课程成绩。</p>
          <div className="daily-actions">
            <button
              className="quiet"
              aria-pressed={marks[item.id] === 'fluent'}
              onClick={() => onMark(item.id, 'fluent')}
            >
              家长判断：熟练
            </button>
            <button
              className="quiet"
              aria-pressed={marks[item.id] === 'again'}
              onClick={() => onMark(item.id, 'again')}
            >
              家长判断：再练一练
            </button>
          </div>
        </details>
        {phase === 'finished' && (
          <div className="daily-summary">
            <p>
              本次练过 {summary.practiced} / {summary.total} 条；家长标记熟练 {summary.parentFluent}{' '}
              条，再练 {summary.parentAgain} 条。只听示范不算跟读完成。
            </p>
            <button onClick={() => select(0)}>再读一遍</button>
          </div>
        )}
      </section>
      <aside className="daily-list" aria-label={`第${day.number}份本节内容`}>
        <h3>本节内容</h3>
        {section.items.map((value, position) => (
          <button
            key={value.id}
            className="quiet"
            aria-current={position === index ? 'step' : undefined}
            onClick={() => {
              select(position);
              if (!guidanceEnabled) void play(false, position);
            }}
          >
            <span>{position + 1}</span>
            <strong>{value.display}</strong>
            <small>
              {marks[value.id] === 'fluent'
                ? '家长：熟练'
                : marks[value.id] === 'again'
                  ? '家长：再练'
                  : marks[value.id]
                    ? '练过'
                    : value.available
                      ? ''
                      : '缺少声音'}
            </small>
          </button>
        ))}
      </aside>
    </div>
  );
}
