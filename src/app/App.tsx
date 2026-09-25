import { useCallback, useEffect, useMemo, useState } from 'react';
import './styles.css';

/* eslint-disable @typescript-eslint/no-explicit-any -- API JSON mirrors the versioned content schema. */
type Json = Record<string, any>;
type Bootstrap = {
  paired: boolean;
  isLocalHost?: boolean;
  device?: { label: string; isParent: boolean };
  profile?: Record<string, unknown>;
};
type Option = { id: string; label: string };
type Lesson = {
  id: string;
  order: number;
  title: string;
  objectives: string[];
  exerciseIds: string[];
  suggestedSessionMinutes?: number;
};
type Exercise = {
  id: string;
  type: string;
  prompt: string;
  options: Option[];
  answer: { optionId: string };
};
type Task = { instanceId: string; exercise: Exercise };
type Session = {
  id: string;
  lessonId: string;
  tasks: Task[];
  results: Record<string, unknown>;
  draftContent: boolean;
};
type Progress = {
  revision: number;
  selectedLessonId: string;
  mastery: { status: string }[];
  attempts: unknown[];
};
type Curriculum = { lessons: Lesson[] };
type Answer = {
  correct: boolean;
  correctOptionId: string;
  selectedOptionId: string;
  mastery: { status: string };
};
type Hint = { explanation: string; answer: { optionId: string } };

async function api(path: string, options: RequestInit = {}): Promise<Json> {
  const headers = new Headers(options.headers);
  if (options.body) headers.set('Content-Type', 'application/json');
  const csrf = document.cookie
    .split('; ')
    .find((item) => item.startsWith('lp_csrf='))
    ?.split('=')
    .slice(1)
    .join('=');
  if (csrf && options.method && options.method !== 'GET')
    headers.set('X-LP-CSRF', decodeURIComponent(csrf));
  const response = await fetch(`/api/v1${path}`, {
    ...options,
    headers,
    credentials: 'same-origin',
  });
  if (response.status === 204) return {};
  const body: Json = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = body.detail as { code?: string } | undefined;
    throw new Error(detail?.code ?? `HTTP_${response.status}`);
  }
  return body;
}

const idempotencyKey = () => crypto.randomUUID();

export function App() {
  const [boot, setBoot] = useState<Bootstrap | null>(null);
  const [curriculum, setCurriculum] = useState<Curriculum | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [session, setSession] = useState<Session | null>(null);
  const [code, setCode] = useState('');
  const [pairCode, setPairCode] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [hint, setHint] = useState<Hint | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [parentOpen, setParentOpen] = useState(false);
  const [lessonChoice, setLessonChoice] = useState('');

  const refresh = useCallback(async () => {
    const state = (await api('/bootstrap')) as Bootstrap;
    setBoot(state);
    if (!state.paired) return;
    const [course, stats, current] = await Promise.all([
      api('/curriculum'),
      api('/profiles/progress'),
      api('/sessions/current'),
    ]);
    const nextStats = stats as Progress;
    setCurriculum(course as Curriculum);
    setProgress(nextStats);
    setSession(current as Session | null);
    setLessonChoice(nextStats.selectedLessonId);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void api('/bootstrap')
      .then(async (result) => {
        const state = result as Bootstrap;
        if (cancelled) return;
        setBoot(state);
        if (!state.paired) return;
        const [course, stats, current] = await Promise.all([
          api('/curriculum'),
          api('/profiles/progress'),
          api('/sessions/current'),
        ]);
        if (cancelled) return;
        const nextStats = stats as Progress;
        setCurriculum(course as Curriculum);
        setProgress(nextStats);
        setSession(current as Session | null);
        setLessonChoice(nextStats.selectedLessonId);
      })
      .catch((reason: Error) => {
        if (!cancelled) setError(reason.message);
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const lessons = useMemo(() => curriculum?.lessons ?? [], [curriculum]);
  const lessonById = useMemo(() => new Map(lessons.map((item) => [item.id, item])), [lessons]);
  const currentLesson = progress ? lessonById.get(progress.selectedLessonId) : undefined;
  const mastery = progress?.mastery ?? [];
  const mastered = mastery.filter((item) => item.status === 'mastered').length;

  async function act(work: () => Promise<void>) {
    setBusy(true);
    setError('');
    try {
      await work();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : '操作失败，请重试。');
    } finally {
      setBusy(false);
    }
  }

  if (!boot) return <main className="loading">正在连接本机学习服务…</main>;
  if (!boot.paired)
    return (
      <main className="pair-page">
        <header className="brand">
          <span className="brand-mark">拼</span>
          <span>爱拼音</span>
        </header>
        <section className="hero-card">
          <div className="hero-orbit" aria-hidden="true">
            ā
          </div>
          <p className="eyebrow">陪孩子慢慢学 · 每次几分钟</p>
          <h1>
            拼音小岛
            <br />
            等你来探索
          </h1>
          <p>在这台 Mac Studio 上运行的家庭学习空间。配对后，学习记录只保存在这台电脑里。</p>
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void act(async () => {
                await api('/pair', {
                  method: 'POST',
                  body: JSON.stringify({ code, label: '学习设备' }),
                });
                setCode('');
                await refresh();
              });
            }}
          >
            <label htmlFor="pair-code">家长配对码</label>
            <div className="pair-input">
              <input
                id="pair-code"
                value={code}
                onChange={(event) => setCode(event.target.value.toUpperCase())}
                maxLength={12}
                autoComplete="one-time-code"
              />
              <button disabled={busy || code.length < 8}>连接家庭</button>
            </div>
          </form>
          {boot.isLocalHost && (
            <div className="local-pair">
              <button
                className="quiet"
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    const result = await api('/local/pairing-code', { method: 'POST' });
                    setPairCode(result.code);
                  })
                }
              >
                在 Mac 上生成家长配对码
              </button>
              {pairCode && (
                <p className="pair-code">
                  {pairCode}
                  <small>5 分钟内一次有效</small>
                </p>
              )}
            </div>
          )}
          <p className="privacy-note">
            🔒 录音不会发送到互联网。当前自动评分尚未通过离线验证，跟读暂未开启。
          </p>
        </section>
        <Notice error={error} />
      </main>
    );

  const active = session;
  const taskIndex = active
    ? active.tasks.findIndex((task: Json) => !active.results?.[task.instanceId])
    : -1;
  const task = active && taskIndex >= 0 ? active.tasks[taskIndex] : null;
  const question = task?.exercise;
  const title =
    (active ? lessonById.get(active.lessonId)?.title : undefined) ?? currentLesson?.title;

  if (active && question)
    return (
      <main className="play-page">
        <nav className="play-nav">
          <button
            className="icon-button"
            aria-label="退出练习"
            onClick={() =>
              void act(async () => {
                await api(`/sessions/${active.id}/finish`, { method: 'POST' });
                setSession(null);
                setAnswer(null);
                await refresh();
              })
            }
          >
            ←
          </button>
          <div>
            <small>拼音小岛 · {title}</small>
            <strong>
              第 {taskIndex + 1} / {active.tasks.length} 关
            </strong>
          </div>
          <span className="progress-dots">
            {active.tasks.map((_: Json, i: number) => (
              <i key={i} className={i < taskIndex ? 'done' : i === taskIndex ? 'now' : ''} />
            ))}
          </span>
        </nav>
        {active.draftContent && (
          <div className="draft-banner">试用课程草稿：题目尚待教师审校，请家长陪伴使用。</div>
        )}
        <section className="question-card">
          <div className="mascot" aria-hidden="true">
            🦊
          </div>
          <p className="eyebrow">{question.type === 'tone-choice' ? '声调观察站' : '拼音发现站'}</p>
          <h1>{question.prompt}</h1>
          <p className="adult-hint">这道题暂时没有标准音频，可请家长读题，不会录音或评分。</p>
          <div className="options" role="group" aria-label="选择答案">
            {question.options.map((option: Json, index: number) => (
              <button
                key={option.id}
                className={`option ${answer ? (option.id === answer.correctOptionId ? 'correct' : option.id === answer.selectedOptionId ? 'wrong' : '') : ''}`}
                disabled={Boolean(answer) || busy}
                onClick={() =>
                  void act(async () => {
                    const result = (await api(`/instances/${task.instanceId}/answer`, {
                      method: 'POST',
                      body: JSON.stringify({
                        requestId: idempotencyKey(),
                        answerOptionId: option.id,
                      }),
                    })) as Omit<Answer, 'correctOptionId' | 'selectedOptionId'>;
                    setAnswer({
                      ...result,
                      correctOptionId: question.answer.optionId,
                      selectedOptionId: option.id,
                    });
                    await refreshProgressOnly();
                  })
                }
              >
                <span className="option-index">{String.fromCharCode(65 + index)}</span>
                {option.label}
              </button>
            ))}
          </div>
          {answer && (
            <div className={`feedback ${answer.correct ? 'good' : 'try-again'}`} role="status">
              <strong>{answer.correct ? '答对啦！' : '没关系，再看看正确答案。'}</strong>
              <span>
                {answer.mastery.status === 'mastered'
                  ? '这个知识点已掌握 ✨'
                  : '完成后继续下一关吧。'}
              </span>
            </div>
          )}
          {!answer && (
            <div className="exercise-actions">
              <button
                className="quiet hint-button"
                disabled={busy}
                onClick={() =>
                  void act(async () =>
                    setHint(
                      (await api(`/instances/${task.instanceId}/hint`, { method: 'POST' })) as Hint,
                    ),
                  )
                }
              >
                给我一点提示
              </button>
              <button
                className="quiet skip-button"
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    await api(`/instances/${task.instanceId}/skip`, { method: 'POST' });
                    setHint(null);
                    setSession((await api('/sessions/current')) as Session);
                  })
                }
              >
                先跳过这题
              </button>
            </div>
          )}
          {hint && !answer && (
            <p className="hint-box">
              {hint.explanation} 答案提示：
              {question.options.find((option: Json) => option.id === hint.answer.optionId)?.label}
            </p>
          )}
          {answer && (
            <button
              className="next-button"
              onClick={() =>
                void act(async () => {
                  setAnswer(null);
                  setHint(null);
                  setSession((await api('/sessions/current')) as Session);
                })
              }
            >
              继续 →
            </button>
          )}
        </section>
        <Notice error={error} />
      </main>
    );
  if (active && taskIndex < 0)
    return (
      <main className="play-page">
        <section className="question-card">
          <div className="mascot">🎉</div>
          <h1>今天的探索完成啦！</h1>
          <p>你认真完成了这一小段练习，休息一下也很好。</p>
          <ul className="session-summary" aria-label="本次练习小结">
            <li>
              独立答对：
              {
                Object.values(active.results as Record<string, Json>).filter(
                  (item) => item.firstTryCorrect,
                ).length
              }{' '}
              题
            </li>
            <li>
              提示后答对：
              {
                Object.values(active.results as Record<string, Json>).filter(
                  (item) => item.correct && !item.firstTryCorrect && !item.skipped,
                ).length
              }{' '}
              题
            </li>
            <li>
              跳过：
              {
                Object.values(active.results as Record<string, Json>).filter((item) => item.skipped)
                  .length
              }{' '}
              题
            </li>
          </ul>
          <button
            onClick={() =>
              void act(async () => {
                await api(`/sessions/${active.id}/finish`, { method: 'POST' });
                setSession(null);
                await refresh();
              })
            }
          >
            回到小岛
          </button>
        </section>
      </main>
    );

  async function refreshProgressOnly() {
    setProgress((await api('/profiles/progress')) as Progress);
  }

  return (
    <main className="home-page">
      <header className="topbar">
        <div className="brand">
          <span className="brand-mark">拼</span>
          <span>爱拼音</span>
        </div>
        <button className="parent-button" onClick={() => setParentOpen(!parentOpen)}>
          {parentOpen ? '返回学习' : '家长管理'}
        </button>
      </header>
      {progress && (
        <>
          <section className="welcome">
            <div>
              <p className="eyebrow">{parentOpen ? '家庭学习空间' : '今天也来探险吧'}</p>
              <h1>
                {parentOpen ? (
                  '家长管理'
                ) : (
                  <>
                    你好，小小拼音家
                    <br />
                    <span>准备好出发了吗？</span>
                  </>
                )}
              </h1>
              <p>{boot.device?.label} · 进度保存在本机 Mac Studio</p>
            </div>
            <div className="welcome-art" aria-hidden="true">
              🌱
            </div>
          </section>
          {parentOpen ? (
            <ParentPanel
              boot={boot}
              curriculum={curriculum}
              progress={progress}
              lessonChoice={lessonChoice}
              setLessonChoice={setLessonChoice}
              refresh={refresh}
              act={act}
            />
          ) : (
            <>
              <section className="journey-card">
                <div className="journey-title">
                  <div>
                    <span className="eyebrow">当前学习</span>
                    <h2>
                      第 {currentLesson?.order ?? 1} 课 · {currentLesson?.title}
                    </h2>
                  </div>
                  <div className="streak">
                    ✦{' '}
                    <span>
                      {mastered}
                      <small>已掌握知识点</small>
                    </span>
                  </div>
                </div>
                <p>{currentLesson?.objectives?.[0]}</p>
                <div className="journey-bottom">
                  <div className="lesson-progress">
                    <span
                      style={{
                        width: `${Math.max(6, Math.round(((currentLesson?.order ?? 1) / lessons.length) * 100))}%`,
                      }}
                    />
                  </div>
                  <span>
                    课程 {currentLesson?.order ?? 1} / {lessons.length}
                  </span>
                </div>
                <button
                  className="start-button"
                  disabled={busy || !currentLesson?.exerciseIds?.length}
                  onClick={() =>
                    void act(async () => {
                      const started = (await api('/sessions', {
                        method: 'POST',
                        body: JSON.stringify({}),
                      })) as Session;
                      setSession(started);
                      setAnswer(null);
                      setHint(null);
                    })
                  }
                >
                  开始今天的练习 <span>→</span>
                </button>
                <p className="session-note">
                  建议陪伴练习约 {currentLesson?.suggestedSessionMinutes ?? 5} 分钟 · 可随时休息
                </p>
              </section>
              <section className="map-card">
                <div className="section-heading">
                  <div>
                    <span className="eyebrow">学习路线</span>
                    <h2>一步一步，点亮拼音</h2>
                  </div>
                  <span className="map-count">{lessons.length} 课</span>
                </div>
                <div className="lesson-grid">
                  {lessons.map((lesson: Json) => {
                    const locked = lesson.order > (currentLesson?.order ?? 1);
                    return (
                      <button
                        key={lesson.id}
                        className={`lesson-tile ${lesson.id === currentLesson?.id ? 'selected' : ''} ${locked ? 'locked' : ''}`}
                        disabled={locked}
                        onClick={() => {
                          setParentOpen(true);
                          setLessonChoice(lesson.id);
                        }}
                      >
                        <span className="tile-number">
                          {locked ? '🔒' : String(lesson.order).padStart(2, '0')}
                        </span>
                        <strong>{lesson.title}</strong>
                        <small>
                          {lesson.order === currentLesson?.order
                            ? '正在学习'
                            : locked
                              ? '之后解锁'
                              : '已开放复习'}
                        </small>
                      </button>
                    );
                  })}
                </div>
              </section>
              <div className="feature-row">
                <div>
                  <span>🎧</span>
                  <strong>标准音频准备中</strong>
                  <small>不使用系统合成音代替</small>
                </div>
                <div>
                  <span>🎙️</span>
                  <strong>离线评分验证中</strong>
                  <small>通过本机验证后开放</small>
                </div>
                <div>
                  <span>🛡️</span>
                  <strong>家庭数据本地保存</strong>
                  <small>不连接第三方云服务</small>
                </div>
              </div>
            </>
          )}
          <footer>
            课程次序按统编人教版一年级上册草案整理，正式学习请以学校教学进度为准。内容仍待教师审校。
          </footer>
        </>
      )}
      <Notice error={error} />
    </main>
  );
}

function ParentPanel({
  boot,
  curriculum,
  progress,
  lessonChoice,
  setLessonChoice,
  refresh,
  act,
}: Json) {
  const [confirm, setConfirm] = useState('');
  const [exportJson, setExportJson] = useState('');
  const [exportRevision, setExportRevision] = useState<number | null>(null);
  const [newDeviceCode, setNewDeviceCode] = useState('');
  return (
    <section className="parent-panel">
      <h2>学习与隐私设置</h2>
      <div className="parent-setting">
        <div>
          <strong>学习进度</strong>
          <p>
            家庭进度修订号 {progress.revision} · {progress.attempts.length} 次练习记录
          </p>
        </div>
        <button
          className="quiet"
          disabled={!boot.device?.isParent}
          onClick={() =>
            void act(async () => {
              const data = await api('/profiles/export');
              setExportJson(JSON.stringify(data, null, 2));
              setExportRevision(progress.revision);
            })
          }
        >
          导出家庭数据
        </button>
      </div>
      <div className="parent-setting">
        <div>
          <strong>当前课程</strong>
          <p>孩子只可学习当前课及之前内容。</p>
        </div>
        <div className="inline-control">
          <select
            value={lessonChoice || progress.selectedLessonId}
            onChange={(event) => setLessonChoice(event.target.value)}
          >
            {curriculum.lessons.map((lesson: Json) => (
              <option key={lesson.id} value={lesson.id}>
                {lesson.order}. {lesson.title}
              </option>
            ))}
          </select>
          <button
            className="quiet"
            disabled={!boot.device?.isParent}
            onClick={() =>
              void act(async () => {
                await api('/household/current-lesson', {
                  method: 'PUT',
                  body: JSON.stringify({
                    lessonId: lessonChoice || progress.selectedLessonId,
                    expectedRevision: progress.revision,
                  }),
                });
                await refresh();
              })
            }
          >
            保存
          </button>
        </div>
      </div>
      <div className="parent-setting">
        <div>
          <strong>录音与自动评分</strong>
          <p>评分服务未通过儿童语音离线验证。不会采集或上传录音。</p>
        </div>
        <span className="status-pill">暂未开启</span>
      </div>
      <div className="parent-setting">
        <div>
          <strong>连接另一台家庭设备</strong>
          <p>生成一次性配对码，在家庭网络内的浏览器输入。</p>
        </div>
        <div>
          <button
            className="quiet"
            disabled={!boot.device?.isParent}
            onClick={() =>
              void act(async () => {
                const result = await api('/pairing-codes', { method: 'POST' });
                setNewDeviceCode(result.code);
              })
            }
          >
            生成配对码
          </button>
          {newDeviceCode && (
            <p className="pair-code">
              {newDeviceCode}
              <small>5 分钟内一次有效</small>
            </p>
          )}
        </div>
      </div>
      {exportJson && exportRevision === progress.revision && (
        <textarea
          className="export-box"
          aria-label="导出的 JSON 数据"
          readOnly
          value={exportJson}
        />
      )}
      <div className="parent-setting danger-setting">
        <div>
          <strong>删除所有学习记录</strong>
          <p>删除后无法恢复。输入“删除我的学习记录”后才会启用。</p>
        </div>
        <input
          aria-label="确认删除文字"
          value={confirm}
          onChange={(event) => setConfirm(event.target.value)}
          placeholder="输入确认文字"
        />
        <button
          className="danger-button"
          disabled={!boot.device?.isParent || confirm !== '删除我的学习记录'}
          onClick={() => {
            if (confirm === '删除我的学习记录')
              void act(async () => {
                await api('/profiles/data', {
                  method: 'DELETE',
                  body: JSON.stringify({ confirmation: confirm }),
                });
                setExportJson('');
                setExportRevision(null);
                setConfirm('');
                await refresh();
              });
          }}
        >
          删除记录
        </button>
      </div>
      <button
        className="quiet"
        onClick={() =>
          void act(async () => {
            await api('/session', { method: 'DELETE' });
            window.location.reload();
          })
        }
      >
        退出此设备配对
      </button>
      {!boot.device?.isParent && <p className="adult-hint">此设备尚未取得家长管理权限。</p>}
    </section>
  );
}

function Notice({ error }: { error: string }) {
  return error ? (
    <p className="error-notice" role="alert">
      操作未完成：{error}。请检查本机服务连接后重试。
    </p>
  ) : null;
}
