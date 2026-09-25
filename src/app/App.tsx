import { useCallback, useEffect, useMemo, useState } from 'react';
import './styles.css';

/* eslint-disable @typescript-eslint/no-explicit-any -- API JSON mirrors the versioned content schema. */
type Json = Record<string, any>;
type Bootstrap = {
  paired: boolean;
  isLocalHost?: boolean;
  device?: { label: string; isParent: boolean };
  profile?: {
    roundsSinceBreak?: number;
    settings?: { reducedMotion?: boolean; soundEnabled?: boolean };
    [key: string]: unknown;
  };
};
type Option = { id: string; label: string };
type Lesson = {
  id: string;
  order: number;
  title: string;
  objectives: string[];
  knowledgeIds: string[];
  exerciseIds: string[];
  suggestedSessionMinutes?: number;
};
type Exercise = {
  id: string;
  type: string;
  prompt: string;
  options: Option[];
};
type Knowledge = {
  id: string;
  lessonId: string;
  category: string;
  symbol: string;
  teachingNote: string;
  reviewStatus: string;
};
type Task = { instanceId: string; exercise: Exercise };
type PendingAnswer = { requestId: string; answerOptionId: string };
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
  settings: { reducedMotion: boolean; soundEnabled: boolean };
  mastery: {
    knowledgeId: string;
    status: string;
    reviewDue: boolean;
    reviewDueDate: string | null;
    sampleSize: number;
    correctCount: number;
  }[];
  attempts: unknown[];
};
type Curriculum = { lessons: Lesson[]; knowledgeItems: Knowledge[]; exercises: Exercise[] };
type Answer = {
  correct: boolean;
  correctOptionId: string;
  selectedOptionId: string;
  mastery: { status: string };
};
type Hint = { explanation: string; answer: { optionId: string } };

const categoryLabels: Record<string, string> = {
  initial: '声母',
  final: '韵母',
  tone: '声调',
  'whole-syllable': '整体认读音节',
  'orthographic-letter': '拼写字母',
  rule: '拼写规则',
};

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
const pendingAnswerKey = (instanceId: string) => `lp.pending-answer.${instanceId}`;

function readPendingAnswer(instanceId: string): PendingAnswer | null {
  try {
    const raw = sessionStorage.getItem(pendingAnswerKey(instanceId));
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<PendingAnswer>;
    return typeof value.requestId === 'string' && typeof value.answerOptionId === 'string'
      ? { requestId: value.requestId, answerOptionId: value.answerOptionId }
      : null;
  } catch {
    return null;
  }
}

function savePendingAnswer(instanceId: string, answer: PendingAnswer) {
  try {
    sessionStorage.setItem(pendingAnswerKey(instanceId), JSON.stringify(answer));
  } catch {
    // Server-side session recovery still prevents scoring the same instance twice.
  }
}

function clearPendingAnswer(instanceId: string) {
  try {
    sessionStorage.removeItem(pendingAnswerKey(instanceId));
  } catch {
    // Storage may be disabled by the browser; the server remains authoritative.
  }
}

async function replayPendingAnswer(session: Session | null): Promise<boolean> {
  if (!session) return false;
  for (const task of session.tasks) {
    const pending = readPendingAnswer(task.instanceId);
    if (!pending) continue;
    if (session.results?.[task.instanceId]) {
      clearPendingAnswer(task.instanceId);
      continue;
    }
    await api(`/instances/${task.instanceId}/answer`, {
      method: 'POST',
      body: JSON.stringify(pending),
    });
    clearPendingAnswer(task.instanceId);
    return true;
  }
  return false;
}

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
  const [lessonViewId, setLessonViewId] = useState<string | null>(null);

  useEffect(() => {
    document.documentElement.dataset.reducedMotion = String(
      Boolean(progress?.settings?.reducedMotion),
    );
  }, [progress?.settings?.reducedMotion]);

  const refresh = useCallback(async () => {
    const state = (await api('/bootstrap')) as Bootstrap;
    setBoot(state);
    if (!state.paired) return;
    const [course, stats, current] = await Promise.all([
      api('/curriculum'),
      api('/profiles/progress'),
      api('/sessions/current'),
    ]);
    const didReplay = await replayPendingAnswer(current as Session | null).catch(() => false);
    const [latestStats, latestCurrent] = didReplay
      ? await Promise.all([api('/profiles/progress'), api('/sessions/current')])
      : [stats, current];
    const nextStats = latestStats as Progress;
    setCurriculum(course as Curriculum);
    setProgress(nextStats);
    setSession(latestCurrent as Session | null);
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
        const didReplay = await replayPendingAnswer(current as Session | null).catch(() => false);
        const [latestStats, latestCurrent] = didReplay
          ? await Promise.all([api('/profiles/progress'), api('/sessions/current')])
          : [stats, current];
        if (cancelled) return;
        const nextStats = latestStats as Progress;
        setCurriculum(course as Curriculum);
        setProgress(nextStats);
        setSession(latestCurrent as Session | null);
        setLessonChoice(nextStats.selectedLessonId);
      })
      .catch((reason: Error) => {
        if (!cancelled) {
          if (reason.message === 'SESSION_EXPIRED' || reason.message === 'PAIRING_REQUIRED')
            setBoot({ paired: false, isLocalHost: false });
          else setError(reason.message);
        }
      });
    return () => {
      cancelled = true;
    };
  }, []);
  const lessons = useMemo(() => curriculum?.lessons ?? [], [curriculum]);
  const lessonById = useMemo(() => new Map(lessons.map((item) => [item.id, item])), [lessons]);
  const currentLesson = progress ? lessonById.get(progress.selectedLessonId) : undefined;
  const canPracticeCurrent = Boolean(
    currentLesson?.exerciseIds.some((exerciseId) =>
      curriculum?.exercises.some(
        (exercise) =>
          exercise.id === exerciseId &&
          ['symbol-choice', 'tone-choice', 'blend-choice'].includes(exercise.type),
      ),
    ),
  );
  const mastery = progress?.mastery ?? [];
  const mastered = mastery.filter((item) => item.status === 'mastered').length;
  const masteryById = new Map(mastery.map((item) => [item.knowledgeId, item]));

  async function act(work: () => Promise<void>) {
    setBusy(true);
    setError('');
    try {
      await work();
    } catch (reason) {
      const message = reason instanceof Error ? reason.message : '操作失败，请重试。';
      if (message === 'SESSION_EXPIRED' || message === 'PAIRING_REQUIRED') {
        setSession(null);
        setBoot({ paired: false, isLocalHost: false });
      } else setError(message);
    } finally {
      setBusy(false);
    }
  }

  async function beginLesson(lessonId: string) {
    const started = (await api('/sessions', {
      method: 'POST',
      body: JSON.stringify({ lessonId }),
    })) as Session;
    setSession(started);
    setAnswer(null);
    setHint(null);
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

  if ((boot.profile?.roundsSinceBreak ?? 0) >= 2)
    return (
      <main className="rest-page">
        <section className="rest-card">
          <div className="mascot" aria-hidden="true">
            🌿
          </div>
          <p className="eyebrow">小小拼音家补充能量</p>
          <h1>连续完成两轮啦！</h1>
          <p>站起来活动一下、喝口水。你可以结束今天的练习，也可以休息后再继续。</p>
          <button
            autoFocus
            onClick={() =>
              void act(async () => {
                await api('/rest/complete', { method: 'POST' });
                await refresh();
              })
            }
          >
            结束今天的练习
          </button>
          <button
            className="quiet"
            disabled={busy}
            onClick={() =>
              void act(async () => {
                await api('/rest/complete', { method: 'POST' });
                await refresh();
              })
            }
          >
            休息好了，继续学习
          </button>
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
          <p className="eyebrow">
            {question.type === 'tone-choice'
              ? '声调观察站'
              : question.type === 'blend-choice'
                ? '拼读组合站'
                : '字形发现站'}
          </p>
          <h1>{question.prompt}</h1>
          <p className="adult-hint">
            {question.type === 'blend-choice'
              ? '请选择一个完整的拼读候选。标准示范音暂未准备，不拼接或播放未审校的字母音。'
              : '这道题暂时没有标准音频，可请家长读题，不会录音或评分。'}
          </p>
          <div
            className={`options ${question.type === 'blend-choice' ? 'blend-options' : ''}`}
            role="group"
            aria-label={question.type === 'blend-choice' ? '完整拼读候选' : '选择答案'}
          >
            {question.options.map((option: Json, index: number) => (
              <button
                key={option.id}
                className={`option ${answer ? (option.id === answer.correctOptionId ? 'correct' : option.id === answer.selectedOptionId ? 'wrong' : '') : ''}`}
                disabled={Boolean(answer) || busy}
                onClick={() =>
                  void act(async () => {
                    let pending = readPendingAnswer(task.instanceId);
                    if (pending && pending.answerOptionId !== option.id)
                      throw new Error('上一题提交结果待确认，请再点一次原来的答案以安全重试。');
                    if (!pending) {
                      pending = { requestId: idempotencyKey(), answerOptionId: option.id };
                      savePendingAnswer(task.instanceId, pending);
                    }
                    const result = (await api(`/instances/${task.instanceId}/answer`, {
                      method: 'POST',
                      body: JSON.stringify(pending),
                    })) as Omit<Answer, 'selectedOptionId'>;
                    clearPendingAnswer(task.instanceId);
                    setAnswer({
                      ...result,
                      selectedOptionId: pending.answerOptionId,
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
              busy={busy}
              refresh={refresh}
              act={act}
            />
          ) : lessonViewId ? (
            <LessonDetail
              lesson={lessonById.get(lessonViewId)}
              knowledge={
                curriculum?.knowledgeItems.filter((item) => item.lessonId === lessonViewId) ?? []
              }
              masteryById={masteryById}
              withinCurrentRange={Boolean(
                lessonById.get(lessonViewId) &&
                currentLesson &&
                lessonById.get(lessonViewId)!.order <= currentLesson.order,
              )}
              canPractice={Boolean(
                lessonById.get(lessonViewId) &&
                currentLesson &&
                lessonById.get(lessonViewId)!.order <= currentLesson.order &&
                lessonById
                  .get(lessonViewId)
                  ?.exerciseIds.some((exerciseId) =>
                    curriculum?.exercises.some(
                      (exercise) =>
                        exercise.id === exerciseId &&
                        ['symbol-choice', 'tone-choice', 'blend-choice'].includes(exercise.type),
                    ),
                  ),
              )}
              onBack={() => setLessonViewId(null)}
              onStart={() =>
                void act(async () => {
                  await beginLesson(lessonViewId);
                  setLessonViewId(null);
                })
              }
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
                  disabled={busy || !canPracticeCurrent}
                  onClick={() =>
                    void act(async () => {
                      await beginLesson(progress.selectedLessonId);
                    })
                  }
                >
                  {canPracticeCurrent ? '开始今天的练习' : '课程资料准备中'} <span>→</span>
                </button>
                {!canPracticeCurrent && (
                  <p className="session-note">当前课尚无可用视觉练习，不会创建空会话。</p>
                )}
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
                    const future = lesson.order > (currentLesson?.order ?? 1);
                    const lessonMastery = (lesson.knowledgeIds as string[])
                      .map((id) => masteryById.get(id))
                      .filter((item) => item !== undefined);
                    const dueCount = lessonMastery.filter((item) => item.reviewDue).length;
                    const masteredCount = lessonMastery.filter(
                      (item) => item.status === 'mastered',
                    ).length;
                    const practiced = lessonMastery.some(
                      (item) => item.sampleSize > 0 || item.status !== 'not-started',
                    );
                    const progressLabel =
                      lessonMastery.length > 0 && masteredCount === lessonMastery.length
                        ? '已掌握'
                        : practiced
                          ? '练习中'
                          : '未开始';
                    return (
                      <button
                        key={lesson.id}
                        className={`lesson-tile ${lesson.id === currentLesson?.id ? 'selected' : ''} ${future ? 'locked' : ''}`}
                        onClick={() => {
                          setLessonViewId(lesson.id);
                        }}
                      >
                        <span className="tile-number">{String(lesson.order).padStart(2, '0')}</span>
                        <strong>{lesson.title}</strong>
                        <small>
                          {future
                            ? '后续课程 · 可预览'
                            : `${lesson.order === currentLesson?.order ? '正在学习 · ' : ''}${progressLabel}`}
                        </small>
                        {dueCount > 0 && (
                          <span className="review-due-badge">到期复习 · {dueCount} 项</span>
                        )}
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

function LessonDetail({
  lesson,
  knowledge,
  masteryById,
  withinCurrentRange,
  canPractice,
  onBack,
  onStart,
}: {
  lesson?: Lesson;
  knowledge: Knowledge[];
  masteryById: Map<string, Progress['mastery'][number]>;
  withinCurrentRange: boolean;
  canPractice: boolean;
  onBack: () => void;
  onStart: () => void;
}) {
  if (!lesson)
    return (
      <section className="lesson-detail" role="status">
        <h2>请选择一课</h2>
        <button className="quiet" onClick={onBack}>
          返回学习路线
        </button>
      </section>
    );
  return (
    <section className="lesson-detail">
      <button className="quiet lesson-back" onClick={onBack}>
        ← 返回学习路线
      </button>
      <p className="eyebrow">第 {lesson.order} 课 · 课程知识卡</p>
      <h2>{lesson.title}</h2>
      <ul className="lesson-objectives">
        {lesson.objectives.map((objective) => (
          <li key={objective}>{objective}</li>
        ))}
      </ul>
      <p className="draft-banner">
        课程草稿，内容待教师审校。标准示范音尚未准备，不使用系统合成音替代。
      </p>
      {knowledge.length > 0 ? (
        <div className="knowledge-grid">
          {knowledge.map((item) => {
            const state = masteryById.get(item.id);
            const statusLabel =
              state?.status === 'mastered'
                ? '已掌握'
                : state?.status === 'practicing'
                  ? '练习中'
                  : '未开始';
            return (
              <article className="knowledge-card" key={item.id}>
                <div className="knowledge-card-meta">
                  <span>{categoryLabels[item.category] ?? '拼音知识'}</span>
                  <span>{statusLabel}</span>
                </div>
                <h3>{item.symbol}</h3>
                {state?.reviewDue && (
                  <p className="review-due-badge">到期复习 · {state.reviewDueDate}</p>
                )}
                <button
                  className="audio-unavailable"
                  disabled
                  aria-label={`${item.symbol} 标准音待准备`}
                >
                  ♫ 标准音待准备
                </button>
                <details>
                  <summary>家长教学提示</summary>
                  <p>{item.teachingNote}</p>
                </details>
              </article>
            );
          })}
        </div>
      ) : (
        <p role="status">这课的知识资料还未准备好。</p>
      )}
      <div className="lesson-detail-actions">
        <button className="start-button" disabled={!canPractice} onClick={onStart}>
          {canPractice ? '开始本课视觉练习 →' : '练习资料尚未准备好'}
        </button>
        {!withinCurrentRange ? (
          <small>这是一课预览。请家长先把当前学习课调整到这里，再开始练习。</small>
        ) : (
          !canPractice && <small>没有可用的视觉练习题，暂不生成练习会话。</small>
        )}
      </div>
    </section>
  );
}

function ParentPanel({
  boot,
  curriculum,
  progress,
  lessonChoice,
  setLessonChoice,
  busy,
  refresh,
  act,
}: Json) {
  const [confirm, setConfirm] = useState('');
  const [resetConfirm, setResetConfirm] = useState('');
  const [exportJson, setExportJson] = useState('');
  const [exportRevision, setExportRevision] = useState<number | null>(null);
  const [importPreview, setImportPreview] = useState<Json | null>(null);
  const [importFileName, setImportFileName] = useState('');
  const [importConfirmation, setImportConfirmation] = useState('');
  const [importComplete, setImportComplete] = useState(false);
  const [newDeviceCode, setNewDeviceCode] = useState('');
  const [devices, setDevices] = useState<Json[]>([]);
  const [revokeDeviceId, setRevokeDeviceId] = useState('');
  const [deviceError, setDeviceError] = useState('');
  const isParent = Boolean(boot.device?.isParent);
  const reloadDevices = useCallback(async () => {
    const result = await api('/devices');
    setDevices(result.devices as Json[]);
  }, []);
  useEffect(() => {
    if (!isParent) return;
    let cancelled = false;
    void api('/devices')
      .then((result) => {
        if (!cancelled) setDevices(result.devices as Json[]);
      })
      .catch((reason: Error) => {
        if (!cancelled) setDeviceError(reason.message);
      });
    return () => {
      cancelled = true;
    };
  }, [isParent]);
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
          <strong>减少动态效果</strong>
          <p>开启后，练习界面停用非必要动画与过渡效果。</p>
        </div>
        <ReducedMotionControl
          key={String(Boolean(progress.settings?.reducedMotion))}
          checked={Boolean(progress.settings?.reducedMotion)}
          disabled={!isParent}
          onChange={(next) =>
            void act(async () => {
              await api('/household/settings', {
                method: 'PUT',
                body: JSON.stringify({
                  soundEnabled: Boolean(progress.settings?.soundEnabled),
                  reducedMotion: next,
                }),
              });
              await refresh();
            })
          }
        />
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
      {isParent && (
        <div className="device-management">
          <div>
            <strong>已连接设备</strong>
            <p>撤销后，该设备下次连接时需要重新配对；学习记录会保留。</p>
          </div>
          <ul className="device-list">
            {devices.map((device) => (
              <li key={device.id}>
                <div>
                  <strong>{device.label}</strong>
                  <small>
                    {device.current ? '本机家长设备' : '家庭设备'} ·{' '}
                    {new Date(device.createdAt).toLocaleDateString('zh-CN')}
                  </small>
                </div>
                {!device.current &&
                  (revokeDeviceId === device.id ? (
                    <div className="device-actions">
                      <button
                        className="danger-button"
                        onClick={() =>
                          void act(async () => {
                            await api(`/devices/${device.id}`, { method: 'DELETE' });
                            setRevokeDeviceId('');
                            await reloadDevices();
                            await refresh();
                          })
                        }
                      >
                        确认撤销
                      </button>
                      <button className="quiet" onClick={() => setRevokeDeviceId('')}>
                        取消
                      </button>
                    </div>
                  ) : (
                    <button className="quiet" onClick={() => setRevokeDeviceId(device.id)}>
                      撤销设备
                    </button>
                  ))}
              </li>
            ))}
          </ul>
          {devices.length === 0 && <p>目前没有已配对设备。</p>}
          {deviceError && <p className="error-notice">设备列表加载失败：{deviceError}</p>}
        </div>
      )}
      {exportJson && exportRevision === progress.revision && (
        <textarea
          className="export-box"
          aria-label="导出的 JSON 数据"
          readOnly
          value={exportJson}
        />
      )}
      <div className="parent-setting import-setting">
        <div>
          <strong>从家庭备份恢复</strong>
          <p>备份只发送到此 Mac Studio 的家庭网络服务，不会发送给第三方。</p>
        </div>
        <label className="file-control">
          选择 JSON 备份
          <input
            aria-label="导入家庭备份文件"
            type="file"
            accept="application/json,.json"
            disabled={!isParent}
            onChange={(event) => {
              const file = event.target.files?.[0];
              event.currentTarget.value = '';
              setImportPreview(null);
              setImportConfirmation('');
              setImportComplete(false);
              if (!file) return;
              void act(async () => {
                if (file.size > 1_048_576) throw new Error('BACKUP_TOO_LARGE');
                const contents = await file.text();
                const result = await api('/profiles/import-preview', {
                  method: 'POST',
                  body: contents,
                });
                setImportFileName(file.name);
                setImportPreview(result);
              });
            }}
          />
        </label>
        {importPreview && (
          <div className="import-preview" aria-label="备份导入预览">
            <strong>{importFileName} · 已通过格式检查</strong>
            {importPreview.migratedFromSchemaVersion && (
              <p>这份 schema v2 备份已迁移；原备份没有休息进度，新轮次计数将从 0 开始。</p>
            )}
            <p>
              将整体替换为 {importPreview.counts.attempts} 条练习、
              {importPreview.counts.sessions} 个会话、
              {importPreview.counts.skippedInstances} 道跳过题和
              {importPreview.counts.reviewPlans} 项复习计划。
            </p>
            <p>此操作会替换本家庭全部学习记录；已经下载的旧备份无法远程删除。</p>
            <label className="import-confirm-label">
              输入“替换家庭学习档案”确认
              <input
                aria-label="确认替换家庭学习档案文字"
                value={importConfirmation}
                onChange={(event) => setImportConfirmation(event.target.value)}
              />
            </label>
            <button
              className="danger-button"
              disabled={!isParent || importConfirmation !== '替换家庭学习档案' || busy}
              onClick={() =>
                void act(async () => {
                  await api('/profiles/import', {
                    method: 'POST',
                    body: JSON.stringify({
                      previewToken: importPreview.previewToken,
                      sha256: importPreview.sha256,
                      expectedRevision: importPreview.revision,
                    }),
                  });
                  setImportPreview(null);
                  setImportConfirmation('');
                  setImportComplete(true);
                  setExportJson('');
                  setExportRevision(null);
                  await refresh();
                })
              }
            >
              确认替换家庭数据
            </button>
          </div>
        )}
        {importComplete && <p role="status">家庭数据已恢复。</p>}
      </div>
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
      <div className="parent-setting danger-setting">
        <div>
          <strong>重置家庭档案</strong>
          <p>
            将删除全家的学习记录和家长设置，并撤销所有浏览器配对、清除未使用的配对码。完成后需在 Mac
            本机重新配对。课程与应用不会卸载；已下载的备份无法远程删除。
          </p>
        </div>
        <input
          aria-label="确认重置家庭档案文字"
          value={resetConfirm}
          onChange={(event) => setResetConfirm(event.target.value)}
          placeholder="输入重置家庭档案"
        />
        <button
          className="danger-button"
          disabled={!isParent || resetConfirm !== '重置家庭档案' || busy}
          onClick={() => {
            if (resetConfirm === '重置家庭档案')
              void act(async () => {
                await api('/profiles/reset', {
                  method: 'DELETE',
                  body: JSON.stringify({ confirmation: resetConfirm }),
                });
                window.location.reload();
              });
          }}
        >
          重置家庭档案
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

function ReducedMotionControl({
  checked,
  disabled,
  onChange,
}: {
  checked: boolean;
  disabled: boolean;
  onChange: (checked: boolean) => void;
}) {
  const [value, setValue] = useState(checked);
  return (
    <label className="setting-toggle">
      <input
        type="checkbox"
        checked={value}
        disabled={disabled}
        onChange={(event) => {
          const next = event.currentTarget.checked;
          setValue(next);
          onChange(next);
        }}
      />
      开启
    </label>
  );
}

function Notice({ error }: { error: string }) {
  return error ? (
    <p className="error-notice" role="alert">
      操作未完成：{error}。请检查本机服务连接后重试。
    </p>
  ) : null;
}
