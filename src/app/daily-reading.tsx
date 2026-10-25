import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react';
import type {
  DailyDay,
  DailyItem,
  DailyReading,
  DailySection,
  ReadingMark,
} from '../domain/daily-reading';
import {
  highlightedSyllable,
  readingGapSeconds,
  readingCharacters,
  readingHanzi,
  sectionSummary,
} from '../domain/daily-reading';
import { audioPlayer } from '../platform/audio/browser-audio-player';
import { BrowserReadingRecorder } from '../platform/audio/browser-reading-recorder';
import { isGuest } from '../platform/guest';
import { recognizeReading, type RecognitionResult } from '../platform/audio/reading-recognition';
import { waitForPlaybackGap } from '../platform/audio/playback-gap';
import { dayResources, itemResources } from '../platform/audio/reading-resources';
import { GuidanceSwitch } from './guidance-switch';
import { useLearningVoice, VoiceButton, VoiceFailure } from './learning-voice';
import { QuickGapSettings } from './quick-gap-settings';
import recognitionContent from '../../content/reading-recognition.json';
import navigationContent from '../../content/daily-reading-navigation.json';

async function readDaily(): Promise<DailyReading> {
  const response = await fetch(`/api/v1/${isGuest() ? 'guest/' : ''}daily-reading`);
  if (!response.ok) throw new Error('DAILY_UNAVAILABLE');
  return response.json() as Promise<DailyReading>;
}

export function DailyReadingPage({
  onBack,
  guidanceEnabled,
  gapSeconds,
  onGuidanceChange,
  onGapChange,
}: {
  onBack: () => void;
  guidanceEnabled: boolean;
  gapSeconds: number;
  onGuidanceChange: (enabled: boolean) => void;
  onGapChange: (seconds: number) => void;
}) {
  const preparation = useSyncExternalStore(
    audioPlayer.readingPool.subscribe,
    audioPlayer.readingPool.status,
  );
  const [data, setData] = useState<DailyReading | null>(null);
  const [error, setError] = useState(false);
  const [dayId, setDayId] = useState('day-01');
  const [sectionId, setSectionId] = useState<string | null>(null);
  const [characterReading, setCharacterReading] = useState(false);
  const helpVoice = useLearningVoice(sectionId ?? 'daily-materials');
  const stopHelpVoice = helpVoice.stop;
  useEffect(() => {
    stopHelpVoice();
  }, [sectionId, stopHelpVoice]);
  const [marks, setMarks] = useState<Record<string, ReadingMark>>({});
  const materialChoices = useRef<HTMLElement | null>(null);
  const sectionTabs = useRef<HTMLDivElement | null>(null);
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
      audioPlayer.releaseReading();
    };
  }, []);
  const day = data?.days.find((value) => value.id === dayId);
  const section = day?.sections.find((value) => value.id === sectionId);
  const sectionIndex = day?.sections.findIndex((value) => value.id === sectionId) ?? -1;
  function chooseSection(id: string) {
    if (id === sectionId) return;
    audioPlayer.stop();
    setSectionId(id);
  }
  function chooseMaterials() {
    audioPlayer.stop();
    setSectionId(null);
    requestAnimationFrame(() =>
      materialChoices.current?.querySelector<HTMLButtonElement>('[aria-pressed="true"]')?.focus(),
    );
  }
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' });
    const tabs = sectionTabs.current;
    const current = tabs?.querySelector<HTMLButtonElement>('[aria-current="step"]');
    if (!tabs || !current) return;
    const keepVisible = () => {
      const bounds = tabs.getBoundingClientRect();
      const target = current.getBoundingClientRect();
      if (target.left < bounds.left + 4) tabs.scrollLeft += target.left - bounds.left - 4;
      else if (target.right > bounds.right - 4) tabs.scrollLeft += target.right - bounds.right + 4;
    };
    keepVisible();
    current.focus({ preventScroll: true });
    const resize = new ResizeObserver(keepVisible);
    resize.observe(tabs);
    return () => resize.disconnect();
  }, [sectionId]);
  useEffect(() => {
    if (!day || !data) return;
    const prepare = () => audioPlayer.prepareReading(dayResources(day, data.ui ?? {}));
    prepare();
    const visibility = () => {
      if (document.hidden) audioPlayer.releaseReading();
      else prepare();
    };
    document.addEventListener('visibilitychange', visibility);
    return () => {
      document.removeEventListener('visibilitychange', visibility);
      audioPlayer.releaseReading();
    };
  }, [day, data]);
  return (
    <section className="daily-page" aria-label="天天练拼音">
      <button className="quiet" onClick={onBack}>
        ← 返回小岛
      </button>
      {!section && (
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
      )}
      {!section && (
        <div className="daily-quick-settings">
          <GuidanceSwitch enabled={guidanceEnabled} onChange={onGuidanceChange} />
          <QuickGapSettings seconds={gapSeconds} onSave={onGapChange} />
        </div>
      )}
      {!section && (
        <details className="daily-parent">
          <summary>跟读怎么玩</summary>
          <VoiceButton id="daily-ui-intro" voice={helpVoice} label="听每日跟读说明" />
          <VoiceFailure voice={helpVoice} />
        </details>
      )}
      {error && (
        <div role="alert">
          暂时连不上每日练习。请检查家庭 Mac。<button onClick={load}>重新连接</button>
        </div>
      )}
      {!data && !error && <p role="status">正在读取每日练习…</p>}
      {data && day && !section && (
        <div className="reading-preparation" aria-label="声音准备">
          <p aria-live="polite">
            本份声音：{preparation.ready} / {preparation.total} 已准备好。
            {preparation.total === 0
              ? '正在准备声音清单…'
              : preparation.ready === preparation.total
                ? '本份声音已就绪。'
                : preparation.failed > 0
                  ? '仍有声音待准备或重试，可以先开始。'
                  : '正在分批准备，可以先开始。'}
          </p>
          {preparation.failed > 0 && (
            <p>
              {preparation.failed} 段声音暂未准备好。
              <button className="quiet" onClick={() => audioPlayer.readingPool.retry()}>
                重试准备声音
              </button>
            </p>
          )}
        </div>
      )}
      {data && day && (
        <>
          {!section && (
            <>
              <nav ref={materialChoices} className="daily-days" aria-label="选择每日练习">
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
              </div>
              <nav className="daily-sections" aria-label="选择练习小节">
                {day.sections.map((value) => {
                  const summary = sectionSummary(value, marks);
                  return (
                    <button
                      key={value.id}
                      className="quiet"
                      aria-pressed={sectionId === value.id}
                      onClick={() => chooseSection(value.id)}
                    >
                      <strong>{value.title}</strong>
                      <small>
                        练过 {summary.practiced} / {summary.total} 条
                      </small>
                    </button>
                  );
                })}
              </nav>
            </>
          )}
          {section && (
            <>
              <div className="daily-session-heading">
                <span>
                  第 {day.number} 份 · 本份小节 {sectionIndex + 1} / {day.sections.length}
                </span>
                <button className="quiet" onClick={chooseMaterials}>
                  换练习
                </button>
              </div>
              <nav className="daily-section-navigation" aria-label="本份小节">
                <button
                  className="quiet daily-section-arrow"
                  disabled={sectionIndex === 0}
                  onClick={() => chooseSection(day.sections[sectionIndex - 1]!.id)}
                  aria-label="上一节"
                >
                  <span aria-hidden="true">←</span>
                  <span>上一节</span>
                </button>
                <div className="daily-section-tabs" ref={sectionTabs}>
                  {day.sections.map((value, position) => {
                    const summary = sectionSummary(value, marks);
                    return (
                      <button
                        key={value.id}
                        className="quiet"
                        aria-current={section.id === value.id ? 'step' : undefined}
                        aria-label={`第 ${position + 1} 节：${value.title}，练过 ${summary.practiced} / ${summary.total} 条`}
                        onClick={() => chooseSection(value.id)}
                      >
                        <span>
                          {position + 1}. {value.title}
                        </span>
                        <small>
                          练过 {summary.practiced} / {summary.total} 条
                        </small>
                      </button>
                    );
                  })}
                </div>
                <button
                  className="quiet daily-section-arrow"
                  disabled={sectionIndex === day.sections.length - 1}
                  onClick={() => chooseSection(day.sections[sectionIndex + 1]!.id)}
                  aria-label="下一节"
                >
                  <span aria-hidden="true">→</span>
                  <span>下一节</span>
                </button>
              </nav>
            </>
          )}
          {section ? (
            <ReadingSession
              key={section.id}
              day={day}
              gapSeconds={gapSeconds}
              guidanceEnabled={guidanceEnabled}
              onGuidanceChange={onGuidanceChange}
              onGapChange={onGapChange}
              section={section}
              characterReading={characterReading}
              onCharacterReadingChange={setCharacterReading}
              onNextSection={
                sectionIndex < day.sections.length - 1
                  ? () => chooseSection(day.sections[sectionIndex + 1]!.id)
                  : undefined
              }
              onChooseMaterials={chooseMaterials}
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
          {section && (
            <div className="reading-preparation daily-preparation-detail" aria-label="声音准备">
              <p>
                {preparation.total > 0 && preparation.ready === preparation.total
                  ? '本份声音已就绪。'
                  : '正在准备声音，可以先开始。'}
              </p>
              {preparation.failed > 0 && (
                <button className="quiet" onClick={() => audioPlayer.readingPool.retry()}>
                  重试准备声音
                </button>
              )}
              <details>
                <summary>声音与练习记录</summary>
                <p>
                  本份声音：{preparation.ready} / {preparation.total}{' '}
                  已准备好。只在当前页面缓存；换份、退出或后台后清除。本次跟读标记退出清除，不计课程成绩。
                </p>
              </details>
            </div>
          )}
        </>
      )}
    </section>
  );
}

function FollowWait({ seconds }: { seconds: number }) {
  const [remaining, setRemaining] = useState(seconds);
  useEffect(() => {
    const end = performance.now() + seconds * 1000;
    const timer = window.setInterval(
      () => setRemaining(Math.max(0, (end - performance.now()) / 1000)),
      100,
    );
    return () => window.clearInterval(timer);
  }, [seconds]);
  return (
    <div className="daily-follow-wait" role="status" aria-label="请跟读">
      <div>
        <span>请跟读</span>
        <span aria-hidden="true">{remaining.toFixed(1)} 秒</span>
      </div>
      <progress max={seconds} value={remaining} aria-label="跟读剩余时间" />
    </div>
  );
}

function ReadingSession({
  day,
  guidanceEnabled,
  gapSeconds,
  onGuidanceChange,
  onGapChange,
  section,
  characterReading,
  onCharacterReadingChange,
  onNextSection,
  onChooseMaterials,
  marks,
  onMark,
}: {
  day: DailyDay;
  guidanceEnabled: boolean;
  gapSeconds: number;
  onGuidanceChange: (enabled: boolean) => void;
  onGapChange: (seconds: number) => void;
  section: DailySection;
  characterReading: boolean;
  onCharacterReadingChange: (enabled: boolean) => void;
  onNextSection?: () => void;
  onChooseMaterials: () => void;
  marks: Record<string, ReadingMark>;
  onMark: (id: string, mark: ReadingMark) => void;
}) {
  const [index, setIndex] = useState(0);
  const [phase, setPhase] = useState<'ready' | 'playing' | 'follow' | 'finished'>('ready');
  const [waiting, setWaiting] = useState<{ seconds: number; id: string } | null>(null);
  const [highlight, setHighlight] = useState(-1);
  const [audioStage, setAudioStage] = useState<'loading' | 'playing'>('loading');
  const [instructionPlaying, setInstructionPlaying] = useState(false);
  const [failure, setFailure] = useState('');
  const [recording, setRecording] = useState<'idle' | 'requesting' | 'recording' | 'stopping'>(
    'idle',
  );
  const [recordError, setRecordError] = useState('');
  const [recordUrl, setRecordUrl] = useState<string | null>(null);
  const [adultOpen, setAdultOpen] = useState(false);
  const [recordOpen, setRecordOpen] = useState(false);
  const [exampleOpen, setExampleOpen] = useState(false);
  const [examplesPlaying, setExamplesPlaying] = useState(false);
  const [exampleFailure, setExampleFailure] = useState(false);
  const [recognizing, setRecognizing] = useState(false);
  const [recognition, setRecognition] = useState<RecognitionResult | null>(null);
  const controller = useRef<AbortController | null>(null);
  const recorder = useRef(new BrowserReadingRecorder());
  const replay = useRef<HTMLAudioElement | null>(null);
  const listRef = useRef<HTMLElement | null>(null);
  const item = section.items[index]!;
  const groups =
    (
      navigationContent as Record<string, { family: string; compact: boolean; itemIds: string[] }[]>
    )[section.id] ?? [];
  useEffect(() => {
    const list = listRef.current;
    const current = list?.querySelector<HTMLElement>('[aria-current="step"]');
    if (!list || !current) return;
    const bounds = list.getBoundingClientRect();
    const target = current.getBoundingClientRect();
    const top = bounds.top + list.clientTop + 8;
    const bottom = bounds.top + list.clientTop + list.clientHeight - 8;
    if (target.top < top) list.scrollTop += target.top - top;
    else if (target.bottom > bottom) list.scrollTop += target.bottom - bottom;
  }, [item.id]);
  useEffect(() => {
    audioPlayer.prioritizeReading([
      { kind: 'voice', id: `daily-instruction-${section.id}` },
      ...section.items.slice(index, index + 2).flatMap(itemResources),
    ]);
  }, [section, index]);
  const previousGuidance = useRef(guidanceEnabled);
  const guidance = useRef(guidanceEnabled);
  guidance.current = guidanceEnabled;
  const stop = useCallback(() => {
    controller.current?.abort();
    controller.current = null;
    audioPlayer.stop();
    setHighlight(-1);
    setExamplesPlaying(false);
    setPhase('ready');
    setWaiting(null);
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

  const playPrivate = (id: string, signal: AbortSignal) => {
    setInstructionPlaying(id.startsWith('daily-instruction-'));
    return audioPlayer.playPrivate(id, signal, { onState: setAudioStage });
  };
  async function demo(target: DailyItem, signal: AbortSignal) {
    setInstructionPlaying(false);
    if (section.kind === 'sentences') {
      const sentence = target.sentenceReading;
      if (!sentence?.available || sentence.timings.length !== target.syllables.length)
        throw new Error('NOT_PREPARED');
      if (characterReading) {
        await audioPlayer.playCharacters(sentence.narrationId, sentence.timings, signal, {
          onState: setAudioStage,
          onSegment: setHighlight,
        });
      } else {
        await audioPlayer.playPrivate(sentence.narrationId, signal, {
          onState: setAudioStage,
          onTime: (seconds) => setHighlight(highlightedSyllable(sentence.timings, seconds)),
        });
      }
      setHighlight(-1);
      return;
    }
    if (!target.narrationId && (target.missingSyllables.length || !target.audioIds.length))
      throw new Error('NOT_PREPARED');
    if (target.narrationId) {
      setHighlight(-1);
      await audioPlayer.playPrivate(target.narrationId, signal, {
        onState: setAudioStage,
        onTime: (seconds) => setHighlight(highlightedSyllable(target.timings ?? [], seconds)),
      });
    } else if (target.audioIds.length > 1) {
      await audioPlayer.playDailySequence(target.audioIds, signal, {
        onSegment: setHighlight,
        onState: setAudioStage,
      });
    } else {
      for (const [position, id] of target.audioIds.entries()) {
        await audioPlayer.playDaily(id, signal, {
          onStart: () => setHighlight(position),
          onState: setAudioStage,
        });
        setHighlight(-1);
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
          setExampleOpen(false);
          setExampleFailure(false);
          setIndex(cursor);
          await demo(target, active.signal);
          if (cursor < section.items.length - 1) {
            const seconds = readingGapSeconds(target, gapSeconds);
            setWaiting({ seconds, id: target.id });
            await waitForPlaybackGap(seconds, active.signal);
            setWaiting(null);
          }
        }
        setPhase('finished');
        if (guidance.current) await playPrivate('daily-ui-done', active.signal);
      } else {
        await demo(section.items[startIndex]!, active.signal);
        if (guidance.current) await playPrivate('daily-ui-follow', active.signal);
        setPhase('follow');
      }
    } catch (error) {
      if (!active.signal.aborted) {
        setHighlight(-1);
        setFailure(readingAudioFailure(error));
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
    setExampleOpen(false);
    setExampleFailure(false);
    setIndex(cursor);
  }
  async function playExamples() {
    if (!item.wordExample) return;
    stop();
    setExampleOpen(true);
    setExampleFailure(false);
    setExamplesPlaying(true);
    setPhase('playing');
    const active = new AbortController();
    controller.current = active;
    try {
      await playPrivate(item.wordExample.id, active.signal);
    } catch {
      if (!active.signal.aborted) setExampleFailure(true);
    } finally {
      if (controller.current === active) {
        controller.current = null;
        setExamplesPlaying(false);
        setPhase('ready');
      }
    }
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
        <div className="daily-quick-settings">
          <GuidanceSwitch enabled={guidanceEnabled} onChange={onGuidanceChange} />
          <QuickGapSettings
            seconds={gapSeconds}
            item={item}
            disabled={recording !== 'idle' || recognizing}
            onSave={(seconds) => {
              stop();
              onGapChange(seconds);
            }}
          />
          {section.kind === 'sentences' && (
            <label className="guidance-switch">
              <input
                type="checkbox"
                checked={characterReading}
                disabled={recording !== 'idle' || recognizing}
                onChange={(event) => {
                  stop();
                  setFailure('');
                  onCharacterReadingChange(event.currentTarget.checked);
                }}
              />
              <span>逐字读</span>
            </label>
          )}
        </div>
        <p>{section.instruction}</p>
        <button
          className={`quiet daily-target${item.syllables.length > 6 ? ' daily-target-sentence' : ''}`}
          aria-label={item.display}
          disabled={recording !== 'idle'}
          onClick={() => void play()}
        >
          {item.syllables.map((syllable, position) => (
            <ruby key={position}>
              <span
                className={highlight === position ? 'daily-highlight' : ''}
                aria-current={highlight === position ? 'true' : undefined}
              >
                {syllable}
              </span>
              {readingCharacters(item.id)[position] && (
                <rt>{readingCharacters(item.id)[position]}</rt>
              )}
            </ruby>
          ))}
        </button>

        <div className="daily-status-strip">
          {waiting ? (
            <FollowWait key={waiting.id} seconds={waiting.seconds} />
          ) : (
            <>
              <p role="status" aria-live="polite">
                {recording === 'requesting'
                  ? '正在准备录音，请允许麦克风…'
                  : recording === 'recording'
                    ? '正在录音，读完点停止。'
                    : recording === 'stopping'
                      ? '正在结束录音…'
                      : phase === 'playing'
                        ? waiting
                          ? '轮到你读啦，可以随时停止。'
                          : audioStage === 'loading'
                            ? '正在准备这段声音，请稍等…'
                            : instructionPlaying
                              ? '正在听本节说明…'
                              : '仔细听一听…'
                        : phase === 'follow'
                          ? '轮到你读啦，读完点下一条。'
                          : phase === 'finished'
                            ? '这一节结束啦，可以休息，也可以再读一遍。'
                            : '点开始跟读，先听示范。'}
              </p>
              <div className="daily-static-track" aria-hidden="true" />
            </>
          )}
        </div>
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
        </div>
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
        <p className="daily-source-kind">
          {section.kind === 'sentences'
            ? characterReading
              ? '逐字读 · 字间留停顿'
              : '整句连读 · 普通话示范'
            : item.narrationId
              ? '中文词句朗读 · 普通话示范'
              : item.derivedAudio
                ? '拼音派生示范 · 一声'
                : '拼音标准音 · 逐音节示范'}
        </p>
        {item.audioNotes.length > 0 && (
          <p className="daily-audio-note">{item.audioNotes.join('；')}</p>
        )}
        {item.wordExample && (
          <div className="daily-word-examples">
            <button
              className="quiet"
              aria-expanded={exampleOpen}
              aria-controls={`${item.id}-examples`}
              disabled={recording !== 'idle' || recognizing}
              onClick={() => {
                if (exampleOpen) {
                  if (examplesPlaying) stop();
                  setExampleOpen(false);
                } else void playExamples();
              }}
            >
              {' '}
              {exampleOpen ? '收起组词样例' : '展开组词样例'}{' '}
            </button>
            {exampleOpen && (
              <div id={`${item.id}-examples`}>
                <p>可以这样组词，也可以想到别的词语。</p>
                <div className="daily-example-words">
                  {item.wordExample.examples.map((example) => (
                    <div key={example.text}>
                      <strong>{example.text}</strong>
                      <span>{example.pinyin}</span>
                    </div>
                  ))}
                </div>
                <button
                  className="quiet"
                  disabled={recording !== 'idle' || recognizing}
                  onClick={() => void playExamples()}
                >
                  再听组词样例
                </button>
                {exampleFailure && <p role="alert">组词声音没有响起来，请点“再听组词样例”重试。</p>}
              </div>
            )}
          </div>
        )}
        <details
          className="daily-optional-recording"
          open={recordOpen}
          onToggle={(event) => {
            setRecordOpen(event.currentTarget.open);
            if (!event.currentTarget.open) clearCapture();
          }}
        >
          <summary>录音比较（可选）</summary>
          <div className="daily-record-actions">
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
            录音仅在浏览器和家庭 Mac
            内存处理，不保存；换条、退出或后台会清除。识别只匹配音节，不判四声。每次识别最多三十秒，录音两分钟自动停止。
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
              <button
                className="quiet"
                disabled={recognizing}
                onClick={() => void judge(recordUrl)}
              >
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
        </details>
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
            <div className="daily-actions">
              <button onClick={onNextSection ?? onChooseMaterials}>
                {onNextSection ? '进入下一节 →' : '返回本份目录'}
              </button>
              <button className="quiet" onClick={() => select(0)}>
                再读一遍
              </button>
            </div>
          </div>
        )}
      </section>
      <aside ref={listRef} className="daily-list" aria-label={`第${day.number}份本节内容`}>
        <h3>本节内容</h3>
        {groups.map((group) => (
          <div className="daily-nav-group" key={group.itemIds[0]}>
            <p className="daily-nav-heading">
              {group.family} · 第{' '}
              {section.items.findIndex((value) => value.id === group.itemIds[0]) + 1}–
              {section.items.findIndex((value) => value.id === group.itemIds.at(-1)) + 1} 条
            </p>
            <div className={group.compact ? 'daily-nav-grid' : 'daily-nav-phrases'}>
              {group.itemIds.map((id) => {
                const position = section.items.findIndex((value) => value.id === id);
                const value = section.items[position]!;
                return (
                  <button
                    key={value.id}
                    className="quiet"
                    aria-current={position === index ? 'step' : undefined}
                    onClick={() => {
                      select(position);
                      void play(false, position);
                    }}
                  >
                    <span>{position + 1}</span>
                    <strong>
                      {value.display}
                      {readingHanzi(value.id) && (
                        <small className="daily-nav-hanzi">{readingHanzi(value.id)}</small>
                      )}
                    </strong>
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
                );
              })}
            </div>
          </div>
        ))}
      </aside>
    </div>
  );
}

function readingAudioFailure(error: unknown): string {
  const code = error instanceof Error ? error.message : '';
  if (code === 'AUDIO_GESTURE_REQUIRED')
    return 'iPad 需要你再点一下播放按钮才能出声，请点“重试示范”。';
  if (code === 'AUDIO_DECODE_FAILED') return '这段声音暂时无法解码，请重试；仍然失败时请家长检查。';
  if (code === 'AUDIO_TIMEOUT' || code === 'AUDIO_NETWORK' || code === 'AUDIO_STALLED')
    return '这段声音下载或播放中断了，请点“重试示范”。已经准备好的声音可以继续播放。';
  if (code.startsWith('AUDIO_HTTP_')) return '这段声音暂时不可用，请重新连接家庭 Mac 后重试。';
  return '示范声音还没响起来，请重试。仍然失败时请家长检查 Mac 上的每日练习音频。';
}
