import { useEffect, useState, useSyncExternalStore } from 'react';
import {
  highlightWords,
  practiceKey,
  type WordPracticeContent,
  type WordMode,
} from '../domain/word-practice';
import { readWordProgress, saveWordProgress } from '../platform/word-practice-progress';
import { GuidanceSwitch } from './guidance-switch';
import { QuickGapSettings } from './quick-gap-settings';
import { WordPlayback } from '../platform/audio/word-playback';
import { audioPlayer } from '../platform/audio/browser-audio-player';
import { WordCoursePicker } from './word-course-picker';
import { WordImage } from './word-image';
import { PinyinLegend, PinyinText, ReadingModeControl } from './pinyin-reading';
import { pinyinSyllables, spellingPlan, type ReadingMode } from '../domain/pinyin-spelling';
import { playSpelling } from '../platform/audio/spelling-playback';
import './word-practice.css';

const modes: { id: WordMode; title: string }[] = [
  { id: 'read', title: '词语拼读' },
  { id: 'write', title: '词语听写' },
  { id: 'recite', title: '课文背诵' },
];
export function WordPractice({
  content: wordPractice,
  contentId,
  spellingSyllables,
  onBack,
  guidanceEnabled,
  onGuidanceChange,
  gapSeconds,
  onGapChange,
}: {
  content: WordPracticeContent;
  contentId: string;
  spellingSyllables: readonly string[];
  onBack: () => void;
  guidanceEnabled: boolean;
  onGuidanceChange: (enabled: boolean) => void;
  gapSeconds: number;
  onGapChange: (seconds: number) => void;
}) {
  const [lessonId, setLessonId] = useState(wordPractice.lessons[0]!.id);
  const [mode, setMode] = useState<WordMode>('read');
  const [readingMode, setReadingMode] = useState<ReadingMode>('direct');
  const [revealed, setRevealed] = useState(false);
  const [index, setIndex] = useState(0);
  const [hidden, setHidden] = useState(false);
  const [selectedText, setSelectedText] = useState('');
  const [notice, setNotice] = useState('');
  const [done, setDone] = useState<string[]>(() => {
    try {
      return readWordProgress(contentId);
    } catch {
      return [];
    }
  });
  const lesson = wordPractice.lessons.find((item) => item.id === lessonId)!;
  const lessonIndex = wordPractice.lessons.indexOf(lesson);
  const [voice] = useState(
    () => new WordPlayback((id, signal) => audioPlayer.playPrivate(id, signal)),
  );
  const playWord = (id: string, signal: AbortSignal) => {
    const word = lesson.read.find((item) => item.audioId === id);
    return readingMode === 'spelling' && word
      ? playSpelling(spellingPlan(pinyinSyllables(word.pinyin), spellingSyllables), id, signal)
      : audioPlayer.playPrivate(id, signal);
  };
  const playback = useSyncExternalStore(voice.subscribe, voice.snapshot);
  useEffect(() => {
    const onHidden = () => {
      if (document.hidden) voice.stop();
    };
    document.addEventListener('visibilitychange', onHidden);
    return () => {
      document.removeEventListener('visibilitychange', onHidden);
      voice.stop();
    };
  }, [voice]);
  useEffect(() => {
    if (!guidanceEnabled && voice.snapshot().playingId?.startsWith('word-ui-')) voice.stop();
  }, [guidanceEnabled, voice]);
  useEffect(
    () =>
      voice.subscribe(() => {
        const word = lesson.read.find((word) => word.audioId === voice.snapshot().playingId);
        if (word) setSelectedText(word.text);
      }),
    [voice, lesson],
  );
  function reset() {
    voice.stop();
    setIndex(0);
    setRevealed(false);
    setHidden(false);
    setNotice('');
    setSelectedText('');
  }
  function selectLesson(id: string) {
    reset();
    setLessonId(id);
  }
  const target = lesson.write[index];
  const selected =
    lesson.read.find((word) => word.audioId === playback.playingId) ??
    lesson.read.find((word) => word.text === selectedText) ??
    lesson.read[0]!;
  const available =
    mode === 'read'
      ? lesson.read.length > 0
      : mode === 'write'
        ? lesson.write.length > 0
        : lesson.passages.length > 0;
  const selectedKey = practiceKey(lesson.id, mode);
  return (
    <section className="word-practice">
      <header className="word-header">
        <button
          className="quiet"
          aria-label="返回首页"
          onClick={() => {
            voice.stop();
            onBack();
          }}
        >
          ←<span>首页</span>
        </button>
        <h1>词语天天练</h1>
        <button
          className="quiet word-intro"
          aria-label="听介绍"
          onClick={() => voice.play('word-ui-welcome')}
        >
          🔊<span>介绍</span>
        </button>
      </header>
      <nav className="word-course-bar" aria-label="选课">
        <button
          aria-label="上一课"
          disabled={lessonIndex === 0}
          onClick={() => selectLesson(wordPractice.lessons[lessonIndex - 1]!.id)}
        >
          ‹
        </button>
        <WordCoursePicker
          lessons={wordPractice.lessons}
          lesson={lesson}
          onSelect={selectLesson}
          onListen={voice.play}
        />
        <button
          aria-label="下一课"
          disabled={lessonIndex === wordPractice.lessons.length - 1}
          onClick={() => selectLesson(wordPractice.lessons[lessonIndex + 1]!.id)}
        >
          ›
        </button>
        <button aria-label="听本课课名" onClick={() => voice.play(lesson.audioId)}>
          🔊
        </button>
      </nav>
      <nav className="word-modes" aria-label="练习分类">
        {modes.map((item) => (
          <button
            key={item.id}
            aria-pressed={mode === item.id}
            onClick={() => {
              reset();
              setMode(item.id);
              if (guidanceEnabled) voice.play(`word-ui-${item.id}`);
            }}
          >
            {item.title}
            <span
              className="word-mode-mark"
              aria-hidden={!done.includes(practiceKey(lesson.id, item.id))}
            >
              {done.includes(practiceKey(lesson.id, item.id)) ? ' ✓' : '\u00a0'}
            </span>
          </button>
        ))}
      </nav>
      <div className="word-toolbar">
        <GuidanceSwitch enabled={guidanceEnabled} onChange={onGuidanceChange} />
        <QuickGapSettings
          seconds={gapSeconds}
          onSave={(seconds) => {
            voice.stop();
            onGapChange(seconds);
          }}
        />
        {mode === 'read' && (
          <ReadingModeControl
            mode={readingMode}
            onChange={(nextMode) => {
              if (nextMode === readingMode) return;
              voice.stop();
              setReadingMode(nextMode);
            }}
          />
        )}
        {mode === 'read' && (
          <button
            className="word-continuous"
            aria-label="连读本课"
            aria-pressed={playback.continuous}
            onClick={() =>
              voice.playSequence(
                lesson.read.map((word) => word.audioId),
                gapSeconds,
                true,
                playWord,
              )
            }
          >
            ▶ 连读本课
          </button>
        )}
        <button aria-label="停止播放" onClick={voice.stop}>
          ■<span> 停止</span>
        </button>
      </div>
      <div className="word-audio-status">
        <p className="word-playback" aria-live="polite">
          {playback.playingId
            ? playback.continuous
              ? `连读 ${playback.index + 1} / ${playback.total}${playback.waiting ? ' · 跟着读一读' : ' · 正在播放…'}`
              : '正在播放…'
            : mode === 'read'
              ? '点词语听读、看图，也可以连读本课。'
              : mode === 'write'
                ? '先听词语，在纸上写好后揭晓。'
                : '听一遍，再试着背一背。'}
        </p>
        <div
          className={`word-audio-error${playback.failureId ? '' : ' word-invisible'}`}
          aria-hidden={!playback.failureId}
          role={playback.failureId ? 'alert' : undefined}
        >
          <span>声音暂时不可用。</span>
          <button onClick={voice.retry} disabled={!playback.failureId}>
            重试声音
          </button>
        </div>
      </div>
      <details className="word-help">
        <summary>玩法与提示</summary>
        <p>{wordPractice.ui[mode]}</p>
        {mode === 'read' && <p>{wordPractice.pinyinNote}</p>}
        <button onClick={() => voice.play(`word-ui-${mode}`)}>🔊 听玩法</button>
      </details>
      {mode === 'read' && <PinyinLegend />}
      {mode === 'read' && (
        <div className="word-reading-layout">
          <WordImage word={selected} />
          <div className="word-grid">
            {lesson.read.map((word) => (
              <button
                key={word.text}
                aria-label={`听读${word.text}`}
                aria-pressed={selected.text === word.text}
                aria-current={playback.playingId === word.audioId ? 'true' : undefined}
                onClick={() => {
                  setSelectedText(word.text);
                  voice.play(word.audioId, playWord);
                }}
              >
                <ruby>
                  {word.text}
                  <rt>
                    <PinyinText value={word.pinyin} />
                  </rt>
                </ruby>
              </button>
            ))}
          </div>
        </div>
      )}
      {mode === 'write' &&
        (target ? (
          <article className="word-dictation">
            <div className="word-dictation-main">
              <p>
                第 {index + 1} / {lesson.write.length} 个词
              </p>
              <button onClick={() => voice.play(target.audioId)}>🔊 听词语 / 重听</button>
              <p className="word-answer" aria-live="polite">
                {revealed ? (
                  <ruby>
                    {target.text}
                    <rt>
                      <PinyinText value={target.pinyin} />
                    </rt>
                  </ruby>
                ) : (
                  '听一听，在纸上写一写'
                )}
              </p>
              <div className="word-dictation-controls">
                <button
                  aria-label="上一个"
                  disabled={index === 0}
                  onClick={() => {
                    voice.stop();
                    setIndex(index - 1);
                    setRevealed(false);
                  }}
                >
                  ‹
                </button>
                <button onClick={() => setRevealed(!revealed)}>
                  {revealed ? '收起答案' : '揭晓答案'}
                </button>
                <button
                  aria-label="下一个"
                  disabled={index === lesson.write.length - 1}
                  onClick={() => {
                    voice.stop();
                    setIndex(index + 1);
                    setRevealed(false);
                  }}
                >
                  ›
                </button>
              </div>
              <small>请和大人核对纸上书写，本练习不自动评分。</small>
            </div>
            <WordImage word={target} concealed={!revealed} />
          </article>
        ) : (
          <p className="word-empty">{wordPractice.ui.emptyWrite}</p>
        ))}
      {mode === 'recite' && (
        <>
          <div className="word-recite-toolbar">
            <button disabled={!lesson.passages.length} onClick={() => setHidden(!hidden)}>
              {hidden ? '显示正文' : '隐藏正文，试着背'}
            </button>
            <span>
              <mark className="word-mark-character">生字</mark> ·{' '}
              <mark className="word-mark-word">本课词语</mark>
            </span>
          </div>
          {!lesson.passages.length && <p className="word-empty">{wordPractice.ui.emptyRecite}</p>}
          {lesson.passages.map((passage) => (
            <article className="word-passage" key={passage.title}>
              <header>
                <div>
                  <h2>{passage.title}</h2>
                  <small>
                    {passage.required
                      ? '材料要求背诵'
                      : passage.readingOnly
                        ? '朗读拓展'
                        : '自选背诵'}{' '}
                    · 教材第 {passage.page} 页
                  </small>
                </div>
                <button
                  onClick={() =>
                    voice.playSequence(passage.paragraphs.map((paragraph) => paragraph.audioId))
                  }
                >
                  🔊 听全文
                </button>
              </header>
              {passage.paragraphs.map((paragraph, i) => (
                <div key={paragraph.audioId} className="word-paragraph">
                  <button
                    aria-label={`听第${i + 1}段`}
                    onClick={() => voice.play(paragraph.audioId)}
                  >
                    🔊<small>{i + 1}</small>
                  </button>
                  <div className="word-text-space">
                    <p className={hidden ? 'word-hidden-text' : ''} aria-hidden={hidden}>
                      {highlightWords(
                        paragraph.text,
                        lesson.read.map((word) => word.text),
                        lesson.characters,
                      ).map((part, j) =>
                        part.kind === 'plain' ? (
                          <span key={j}>{part.text}</span>
                        ) : (
                          <mark className={`word-mark-${part.kind}`} key={j}>
                            {part.text}
                          </mark>
                        ),
                      )}
                    </p>
                    {hidden && (
                      <span className="word-hidden-prompt">正文已隐藏，听一听再背一背。</span>
                    )}
                  </div>
                </div>
              ))}
            </article>
          ))}
          <details className="word-vocabulary">
            <summary>本课生字词 · 点字听读</summary>
            <h3>生字</h3>
            <div className="word-character-list">
              {lesson.characterItems.map((item) => (
                <button
                  key={item.text}
                  aria-label={`听${item.text}，示例${item.example}`}
                  onClick={() => voice.play(item.audioId)}
                >
                  {item.text}
                </button>
              ))}
            </div>
            <h3>词语</h3>
            <div className="word-character-list">
              {lesson.read.map((item) => (
                <button key={item.text} onClick={() => voice.play(item.audioId)}>
                  {item.text}
                </button>
              ))}
            </div>
          </details>
        </>
      )}
      <footer className="word-footer">
        {available && (
          <button
            className="word-complete"
            disabled={done.includes(selectedKey)}
            onClick={() => {
              const next = [...new Set([...done, selectedKey])];
              try {
                saveWordProgress(next, contentId);
                setDone(next);
                setNotice('已记录本次练习。');
              } catch {
                setNotice('设备存储不可用，练习记录未保存，请重试。');
              }
            }}
          >
            {done.includes(selectedKey) ? '本部分已练习 ✓' : '这部分我练习过了'}
          </button>
        )}
        <span className="word-save-status" role="status">
          {notice}
        </span>
      </footer>
      <details className="word-about">
        <summary>记录与材料来源</summary>
        <p>练习标记仅保存在当前设备；访客退出后清除，不计入拼音成绩或同步家庭档案。</p>
        {wordPractice.source.textbook ? (
          <>
            <p>
              词目来自家长提供的《{wordPractice.source.file}》，本课在第 {lesson.page}{' '}
              页；补充课文及生字依据{wordPractice.source.edition}。
            </p>
            <a href={wordPractice.source.textbook} target="_blank" rel="noreferrer">
              查看国家智慧教育平台教材
            </a>
          </>
        ) : (
          <p>词目与阅读短文由爱拼音自编。插图为原创情景示意。</p>
        )}
      </details>
    </section>
  );
}
