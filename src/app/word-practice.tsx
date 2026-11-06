import { useState } from 'react';
import { highlightWords, practiceKey, wordPractice, type WordMode } from '../domain/word-practice';
import { readWordProgress, saveWordProgress } from '../platform/word-practice-progress';
import { useLearningVoice, VoiceFailure } from './learning-voice';
import './word-practice.css';

const modes: { id: WordMode; title: string }[] = [
  { id: 'read', title: '词语拼读' },
  { id: 'write', title: '词语听写' },
  { id: 'recite', title: '课文背诵' },
];
export function WordPractice({ onBack }: { onBack: () => void }) {
  const [lessonId, setLessonId] = useState(wordPractice.lessons[0]!.id);
  const [mode, setMode] = useState<WordMode>('read');
  const [revealed, setRevealed] = useState(false);
  const [index, setIndex] = useState(0);
  const [hidden, setHidden] = useState(false);
  const [notice, setNotice] = useState('');
  const [done, setDone] = useState<string[]>(() => {
    try {
      return readWordProgress();
    } catch {
      return [];
    }
  });
  const lesson = wordPractice.lessons.find((item) => item.id === lessonId)!;
  const voice = useLearningVoice('word-practice');
  function reset() {
    voice.stop();
    setIndex(0);
    setRevealed(false);
    setHidden(false);
    setNotice('');
  }
  const target = lesson.write[index];
  const available =
    mode === 'read'
      ? lesson.read.length > 0
      : mode === 'write'
        ? lesson.write.length > 0
        : lesson.passages.length > 0;
  const selectedKey = practiceKey(lesson.id, mode);
  return (
    <section className="word-practice">
      <header className="section-heading">
        <button
          className="quiet"
          onClick={() => {
            voice.stop();
            onBack();
          }}
        >
          ← 返回首页
        </button>
        <h1>词语天天练</h1>
        <button onClick={() => voice.play('word-ui-welcome')}>🔊 听介绍</button>
      </header>
      <p>一年级上册 · 对应课文练习</p>
      <label>
        选择课程{' '}
        <select
          value={lessonId}
          onChange={(event) => {
            reset();
            setLessonId(event.target.value);
          }}
        >
          {wordPractice.lessons.map((item, i) => (
            <option key={item.id} value={item.id}>
              {i + 1}. {item.title}
            </option>
          ))}
        </select>
      </label>
      <nav className="word-course-nav" aria-label="选课">
        <button
          disabled={lesson === wordPractice.lessons[0]}
          onClick={() => {
            reset();
            setLessonId(wordPractice.lessons[wordPractice.lessons.indexOf(lesson) - 1]!.id);
          }}
        >
          上一课
        </button>
        <button onClick={() => voice.play(lesson.audioId)}>🔊 听课名</button>
        <button
          disabled={lesson === wordPractice.lessons.at(-1)}
          onClick={() => {
            reset();
            setLessonId(wordPractice.lessons[wordPractice.lessons.indexOf(lesson) + 1]!.id);
          }}
        >
          下一课
        </button>
      </nav>
      <h2>{lesson.title}</h2>
      <nav className="word-modes" aria-label="练习分类">
        {modes.map((item) => (
          <button
            key={item.id}
            aria-pressed={mode === item.id}
            onClick={() => {
              reset();
              setMode(item.id);
              voice.play(`word-ui-${item.id}`);
            }}
          >
            {item.title}
            {done.includes(practiceKey(lesson.id, item.id)) ? ' ✓' : ''}
          </button>
        ))}
      </nav>
      <p>{wordPractice.ui[mode]}</p>
      {mode === 'read' && <p>{wordPractice.pinyinNote}</p>}
      <button className="quiet" onClick={() => voice.play(`word-ui-${mode}`)}>
        🔊 听玩法
      </button>{' '}
      <button className="quiet" onClick={voice.stop}>
        停止播放
      </button>
      <p className="word-playback" aria-live="polite">
        {voice.playingId ? '正在播放…' : ''}
      </p>
      <VoiceFailure voice={voice} />
      {mode === 'read' && (
        <div className="word-grid">
          {lesson.read.map((word) => (
            <button
              key={word.text}
              aria-label={`听读${word.text}`}
              onClick={() => voice.play(word.audioId)}
            >
              <ruby>
                {word.text}
                <rt>{word.pinyin}</rt>
              </ruby>
              <span aria-hidden="true"> 🔊</span>
            </button>
          ))}
        </div>
      )}
      {mode === 'write' &&
        (target ? (
          <article className="word-dictation">
            <p>
              第 {index + 1} / {lesson.write.length} 个词
            </p>
            <button onClick={() => voice.play(target.audioId)}>🔊 听词语 / 重听</button>
            <p className="word-answer" aria-live="polite">
              {revealed ? (
                <ruby>
                  {target.text}
                  <rt>{target.pinyin}</rt>
                </ruby>
              ) : (
                '听一听，在纸上写一写'
              )}
            </p>
            <button onClick={() => setRevealed(!revealed)}>
              {revealed ? '收起答案' : '揭晓答案'}
            </button>
            <nav className="word-course-nav">
              <button
                disabled={index === 0}
                onClick={() => {
                  voice.stop();
                  setIndex(index - 1);
                  setRevealed(false);
                }}
              >
                上一个
              </button>
              <button
                disabled={index === lesson.write.length - 1}
                onClick={() => {
                  voice.stop();
                  setIndex(index + 1);
                  setRevealed(false);
                }}
              >
                下一个
              </button>
            </nav>
            <p>请和大人核对纸上书写，本练习不自动评分。</p>
          </article>
        ) : (
          <p>{wordPractice.ui.emptyWrite}</p>
        ))}
      {mode === 'recite' && (
        <>
          {!lesson.passages.length && <p>{wordPractice.ui.emptyRecite}</p>}
          <aside className="word-vocabulary">
            <h3>本课生字</h3>
            <p>点字听读；多音字用组词示范。橙色标记生字，绿色标记材料中的词语。</p>
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
            <h3>本课词语</h3>
            <div className="word-character-list">
              {lesson.read.map((item) => (
                <button key={item.text} onClick={() => voice.play(item.audioId)}>
                  {item.text}
                </button>
              ))}
            </div>
          </aside>
          {lesson.passages.length > 0 && (
            <button onClick={() => setHidden(!hidden)}>
              {hidden ? '显示正文' : '隐藏正文，试着背'}
            </button>
          )}
          {lesson.passages.map((passage) => (
            <article className="word-passage" key={passage.title}>
              <h3>{passage.title}</h3>
              <p>
                {passage.required
                  ? '材料要求背诵'
                  : passage.readingOnly
                    ? '材料要求读一读 · 朗读拓展'
                    : '自选背诵'}{' '}
                · 教材第 {passage.page} 页
              </p>
              <button
                onClick={() =>
                  voice.playSequence(
                    passage.paragraphs.map((paragraph) => ({
                      id: paragraph.audioId,
                      kind: 'private' as const,
                    })),
                  )
                }
              >
                🔊 听全文
              </button>
              {passage.paragraphs.map((paragraph, i) => (
                <div key={paragraph.audioId} className="word-paragraph">
                  <button
                    aria-label={`听第${i + 1}段`}
                    onClick={() => voice.play(paragraph.audioId)}
                  >
                    🔊 {i + 1}
                  </button>
                  {hidden ? (
                    <p>正文已隐藏，听一听再背一背。</p>
                  ) : (
                    <p>
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
                  )}
                </div>
              ))}
            </article>
          ))}
        </>
      )}
      {available && (
        <button
          className="word-complete"
          disabled={done.includes(selectedKey)}
          onClick={() => {
            const next = [...new Set([...done, selectedKey])];
            try {
              saveWordProgress(next);
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
      <p role="status">{notice}</p>
      <p className="word-record-note">
        练习标记仅保存在当前设备；访客退出后清除。不会计入拼音成绩或同步家庭档案。
      </p>
      <details>
        <summary>材料与教材来源</summary>
        <p>
          词目来自家长提供的《{wordPractice.source.file}》，本课位于第 {lesson.page}{' '}
          页；补充课文及生字依据{wordPractice.source.edition}。
        </p>
        <a href={wordPractice.source.textbook} target="_blank" rel="noreferrer">
          查看国家智慧教育平台教材
        </a>
        <p>教材与练习材料保留各自权利。</p>
      </details>
    </section>
  );
}
