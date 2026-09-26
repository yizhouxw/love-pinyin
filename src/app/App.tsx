import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { pinyinTone, splitPinyinCandidate } from '../domain/pinyin-presentation';
import { audioPlayer } from '../platform/audio/browser-audio-player';
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
  lessonId?: string;
  reviewKnowledgeId?: string | null;
  tasks: Task[];
  results: Record<string, unknown>;
  draftContent: boolean;
};
type Progress = {
  revision: number;
  selectedLessonId: string;
  completedSessions: number;
  clockSkewDetected?: boolean;
  pendingClockAttempts?: number;
  attemptCount?: number;
  settings: { reducedMotion: boolean; soundEnabled: boolean };
  mastery: {
    knowledgeId: string;
    status: string;
    reviewDue: boolean;
    reviewDueDate: string | null;
    sampleSize: number;
    correctCount: number;
    accuracy: number | null;
    coveredModes: string[];
    requiredModes: string[];
  }[];
  reviewRecommendations?: {
    knowledgeId: string;
    symbol: string;
    lessonId: string;
    lessonTitle: string;
    dueDate: string;
    overdueDays: number;
  }[];
};
type AttemptRecord = {
  id: string;
  mode: string;
  firstTryCorrect: boolean;
  hintUsed: boolean;
  occurredAt: string;
  dueCredit: boolean;
  clockPending: boolean;
};
type AttemptHistoryPage = {
  items: AttemptRecord[];
  nextCursor: string | null;
  loaded: boolean;
  loading: boolean;
  error: boolean;
};
type Curriculum = {
  lessons: Lesson[];
  knowledgeItems: Knowledge[];
  exercises: Exercise[];
  audioRequirements: AudioRequirement[];
  inventory?: { initials: string[] };
};
type AudioRequirement = {
  id: string;
  knowledgeIds: string[];
  status: string;
  reviewStatus: string;
  file: string | null;
  sha256?: string;
  rightsEvidence?: string;
  reviewEvidence?: string;
};
type Answer = {
  correct: boolean;
  correctOptionId: string;
  selectedOptionId: string;
  mastery: { status: string };
  clockPending?: boolean;
};
type Hint = { explanation: string; answer: { optionId: string } };

function GameOptionContent({
  type,
  label,
  initials,
}: {
  type: string;
  label: string;
  initials: string[];
}) {
  if (type === 'blend-choice') {
    const parts = splitPinyinCandidate(label, initials);
    return (
      <span className="blend-choice-content">
        {parts ? (
          <span className="blend-pieces" aria-hidden="true">
            <span className="blend-piece">
              <small>拼音开头</small>
              <strong>{parts.onset}</strong>
            </span>
            <span className="blend-join">＋</span>
            <span className="blend-piece">
              <small>韵母</small>
              <strong>{parts.rime}</strong>
            </span>
          </span>
        ) : (
          <span className="blend-whole" aria-hidden="true">
            {label}
          </span>
        )}
        <span className="screen-reader-only">拼读候选 {label}</span>
      </span>
    );
  }
  if (type === 'tone-choice') {
    const tone = pinyinTone(label);
    const paths: Record<number, string> = {
      1: 'M5 12 L35 12',
      2: 'M5 27 L35 10',
      3: 'M5 13 Q20 33 35 13',
      4: 'M5 10 L35 28',
    };
    return (
      <span className="tone-choice-content">
        {tone && (
          <svg aria-hidden="true" viewBox="0 0 40 38" className="tone-contour">
            <path d={paths[tone]} />
          </svg>
        )}
        <span className="tone-choice-label">{label}</span>
      </span>
    );
  }
  if (
    type === 'symbol-choice' &&
    [...label].length <= 3 &&
    /^[a-züāáǎàōóǒòēéěèīíǐìūúǔùǖǘǚǜ]+$/u.test(label)
  ) {
    return (
      <span className="symbol-card-content">
        <span className="four-line-card" aria-hidden="true">
          {label}
        </span>
        <span className="screen-reader-only">拼音字形 {label}</span>
      </span>
    );
  }
  return <span className="plain-option-label">{label}</span>;
}

const categoryLabels: Record<string, string> = {
  initial: '声母',
  final: '韵母',
  tone: '声调',
  'whole-syllable': '整体认读音节',
  'orthographic-letter': '拼写字母',
  rule: '拼写规则',
};
const exerciseModeLabels: Record<string, string> = {
  'listen-choice': '听辨',
  'symbol-choice': '字形',
  'tone-choice': '声调',
  'blend-choice': '拼读',
};

function attemptOutcome(attempt: AttemptRecord) {
  if (attempt.clockPending) return '待校时，不计入掌握度';
  if (!attempt.dueCredit) return '日内重复练习，不计入掌握样本';
  if (attempt.firstTryCorrect) return '独立首次答对';
  if (attempt.hintUsed) return '使用过提示，未独立首次答对';
  return '首次未独立答对';
}

function formatAttemptTime(value: string) {
  const date = new Date(value);
  if (Number.isNaN(date.valueOf())) return '时间未知';
  return new Intl.DateTimeFormat('zh-CN', {
    timeZone: 'Asia/Shanghai',
    year: 'numeric',
    month: 'numeric',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
  }).format(date);
}

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
  let response: Response;
  try {
    response = await fetch(`/api/v1${path}`, {
      ...options,
      headers,
      credentials: 'same-origin',
    });
  } catch {
    throw new Error('MAC_UNREACHABLE');
  }
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
  const [parentGateOpen, setParentGateOpen] = useState(false);
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
    const nextCourse = course as Curriculum;
    setCurriculum(nextCourse);
    setProgress(nextStats);
    setSession(latestCurrent as Session | null);
    setLessonChoice(
      nextCourse.lessons.some((lesson) => lesson.id === nextStats.selectedLessonId)
        ? (nextStats.selectedLessonId ?? '')
        : '',
    );
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
        const nextCourse = course as Curriculum;
        setCurriculum(nextCourse);
        setProgress(nextStats);
        setSession(latestCurrent as Session | null);
        setLessonChoice(
          nextCourse.lessons.some((lesson) => lesson.id === nextStats.selectedLessonId)
            ? (nextStats.selectedLessonId ?? '')
            : '',
        );
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
  const currentLesson = progress?.selectedLessonId
    ? lessonById.get(progress.selectedLessonId)
    : undefined;
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

  async function beginReview(knowledgeId: string) {
    const started = (await api(`/reviews/${encodeURIComponent(knowledgeId)}/sessions`, {
      method: 'POST',
      body: JSON.stringify({}),
    })) as Session;
    setSession(started);
    setAnswer(null);
    setHint(null);
  }

  if (!boot)
    return (
      <main className="loading">
        {error ? (
          <>
            <h1>暂时连不上家庭 Mac Studio</h1>
            <p>检查 Mac 和家庭局域网后，可以在这里重新连接。</p>
            <Notice error={error} onReconnect={() => void act(refresh)} />
          </>
        ) : (
          '正在连接本机学习服务…'
        )}
      </main>
    );
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
        <Notice error={error} onReconnect={() => void act(refresh)} />
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
        <Notice error={error} onReconnect={() => void act(refresh)} />
      </main>
    );

  const active = session;
  const taskIndex = active
    ? active.tasks.findIndex((task: Json) => !active.results?.[task.instanceId])
    : -1;
  const task = active && taskIndex >= 0 ? active.tasks[taskIndex] : null;
  const question = task?.exercise;
  const title =
    (active?.reviewKnowledgeId
      ? '两题复习'
      : active
        ? lessonById.get(active.lessonId ?? '')?.title
        : undefined) ?? currentLesson?.title;

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
        {active.tasks.length < 6 && (
          <p className="session-size-note" role="status">
            本课目前准备了 {active.tasks.length} 道可用练习，本轮先完成这些。
          </p>
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
                className={`option game-option ${question.type} ${answer ? (option.id === answer.correctOptionId ? 'correct' : option.id === answer.selectedOptionId ? 'wrong' : '') : ''}`}
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
                <GameOptionContent
                  type={question.type}
                  label={option.label}
                  initials={curriculum?.inventory?.initials ?? []}
                />
              </button>
            ))}
          </div>
          {answer && (
            <div className={`feedback ${answer.correct ? 'good' : 'try-again'}`} role="status">
              <strong>{answer.correct ? '答对啦！' : '没关系，再看看正确答案。'}</strong>
              <span>
                {answer.clockPending
                  ? '此练习已保存为待校时记录，不计入掌握度。'
                  : answer.mastery.status === 'mastered'
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
        <Notice error={error} onReconnect={() => void act(refresh)} />
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
        <button
          className="parent-button"
          onClick={() => {
            if (parentOpen) setParentOpen(false);
            else setParentGateOpen(true);
          }}
        >
          {parentOpen ? '返回学习' : '家长管理'}
        </button>
      </header>
      <AdultConfirmDialog
        open={parentGateOpen}
        onConfirm={() => {
          setParentGateOpen(false);
          setParentOpen(true);
        }}
        onCancel={() => setParentGateOpen(false)}
      />
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
          {!parentOpen && progress.clockSkewDetected && (
            <div className="error-notice" role="alert">
              Mac Studio
              时间似乎回退了。练习仍可继续，但新记录暂不计入掌握度；请家长检查服务器时间。
            </div>
          )}
          {!parentOpen && (
            <section className="garden-card" aria-labelledby="garden-title">
              <div className="garden-copy">
                <span className="eyebrow">拼音花园</span>
                <h2 id="garden-title">每完成一轮，花园多一片叶子</h2>
                <p>这里记录认真参与的每一轮。答错、休息或提前结束都不会失去已经长出的叶子。</p>
              </div>
              <div
                className="garden-pot"
                role="img"
                aria-label={`拼音花园已长出 ${progress.completedSessions} 片叶子`}
              >
                <div className="garden-stem" aria-hidden="true">
                  {Array.from({ length: Math.min(progress.completedSessions, 8) }, (_, index) => (
                    <span className="garden-leaf" key={index} />
                  ))}
                </div>
                <div className="garden-soil" aria-hidden="true" />
                <div className="garden-planter" aria-hidden="true" />
                <strong>{progress.completedSessions} 片叶子</strong>
              </div>
            </section>
          )}
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
              key={lessonViewId}
              lesson={lessonById.get(lessonViewId)}
              knowledge={
                curriculum?.knowledgeItems.filter((item) => item.lessonId === lessonViewId) ?? []
              }
              audioRequirements={curriculum?.audioRequirements ?? []}
              masteryById={masteryById}
              busy={busy}
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
              onReview={(knowledgeId: string) =>
                void act(async () => {
                  await beginReview(knowledgeId);
                  setLessonViewId(null);
                })
              }
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
                      {currentLesson
                        ? `第 ${currentLesson.order} 课 · ${currentLesson.title}`
                        : '请选择当前课'}
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
                <p>
                  {currentLesson?.objectives?.[0] ??
                    '保存的当前课不在此课程版本中。已有学习记录会保留，请家长重新选择学校正在学习的课程。'}
                </p>
                <div className="journey-bottom">
                  <div className="lesson-progress">
                    <span
                      style={{
                        width: currentLesson
                          ? `${Math.max(6, Math.round((currentLesson.order / lessons.length) * 100))}%`
                          : '0%',
                      }}
                    />
                  </div>
                  <span>
                    {currentLesson
                      ? `课程 ${currentLesson.order} / ${lessons.length}`
                      : `共 ${lessons.length} 课 · 当前课待选择`}
                  </span>
                </div>
                <button
                  className="start-button"
                  disabled={busy || !currentLesson || !canPracticeCurrent}
                  onClick={() =>
                    void act(async () => {
                      await beginLesson(progress.selectedLessonId);
                    })
                  }
                >
                  {!currentLesson
                    ? '请家长先选择当前课'
                    : canPracticeCurrent
                      ? '开始今天的练习'
                      : '课程资料准备中'}{' '}
                  <span>→</span>
                </button>
                {!currentLesson ? (
                  <p className="session-note">学习路线仍可浏览，选择当前课后即可继续练习。</p>
                ) : !canPracticeCurrent ? (
                  <p className="session-note">当前课尚无可用视觉练习，不会创建空会话。</p>
                ) : null}
                <p className="session-note">
                  建议陪伴练习约 {currentLesson?.suggestedSessionMinutes ?? 5} 分钟 · 可随时休息
                </p>
              </section>
              {(progress.reviewRecommendations ?? []).length > 0 && (
                <section className="map-card review-recommendations" aria-label="今日推荐复习">
                  <div className="section-heading">
                    <div>
                      <span className="eyebrow">逾期优先 · 每次两题</span>
                      <h2>今日推荐复习</h2>
                    </div>
                    <span className="map-count">最多 3 项</span>
                  </div>
                  <div className="recommendation-list">
                    {progress.reviewRecommendations!.map((recommendation) => (
                      <article className="recommendation-item" key={recommendation.knowledgeId}>
                        <div>
                          <strong>{recommendation.symbol}</strong>
                          <span>{recommendation.lessonTitle}</span>
                          <small>
                            {recommendation.overdueDays > 0
                              ? `已逾期 ${recommendation.overdueDays} 天`
                              : '今天到期'}
                          </small>
                        </div>
                        <button
                          className="review-start-button"
                          disabled={busy}
                          onClick={() =>
                            void act(async () => {
                              await beginReview(recommendation.knowledgeId);
                            })
                          }
                        >
                          开始复习 →
                        </button>
                      </article>
                    ))}
                  </div>
                </section>
              )}
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
                    const future = !currentLesson || lesson.order > currentLesson.order;
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
      <Notice error={error} onReconnect={() => void act(refresh)} />
    </main>
  );
}

function LessonDetail({
  lesson,
  knowledge,
  audioRequirements,
  masteryById,
  busy,
  withinCurrentRange,
  canPractice,
  onBack,
  onReview,
  onStart,
}: {
  lesson?: Lesson;
  knowledge: Knowledge[];
  audioRequirements: AudioRequirement[];
  masteryById: Map<string, Progress['mastery'][number]>;
  busy: boolean;
  withinCurrentRange: boolean;
  canPractice: boolean;
  onBack: () => void;
  onReview: (knowledgeId: string) => void;
  onStart: () => void;
}) {
  const [playingAudioId, setPlayingAudioId] = useState<string | null>(null);
  const [audioFailureId, setAudioFailureId] = useState<string | null>(null);
  const playback = useRef<{ audioId: string; controller: AbortController } | null>(null);
  const releasePlayback = useCallback(() => {
    const active = playback.current;
    playback.current = null;
    active?.controller.abort();
    audioPlayer.stop();
  }, []);
  const stopPlayback = useCallback(() => {
    releasePlayback();
    setPlayingAudioId(null);
  }, [releasePlayback]);

  useEffect(() => {
    const stopWhenHidden = () => {
      if (document.hidden) stopPlayback();
    };
    document.addEventListener('visibilitychange', stopWhenHidden);
    return () => {
      document.removeEventListener('visibilitychange', stopWhenHidden);
      releasePlayback();
    };
  }, [releasePlayback, stopPlayback]);

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
        课程资料草稿，教学内容待教师审校。只播放有登记且审校通过的标准音，不使用系统合成音替代。
      </p>
      {knowledge.length > 0 ? (
        <div className="knowledge-grid">
          {knowledge.map((item) => {
            const state = masteryById.get(item.id);
            const audio = audioRequirements.find(
              (asset) =>
                asset.knowledgeIds.includes(item.id) &&
                asset.status === 'approved' &&
                asset.reviewStatus === 'approved' &&
                Boolean(asset.file && asset.sha256 && asset.rightsEvidence && asset.reviewEvidence),
            );
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
                  <>
                    <p className="review-due-badge">到期复习 · {state.reviewDueDate}</p>
                    <button
                      className="quiet"
                      disabled={busy || !withinCurrentRange}
                      onClick={() => onReview(item.id)}
                    >
                      开始两题复习
                    </button>
                  </>
                )}
                {audio ? (
                  <button
                    className="audio-play-button"
                    aria-label={`${item.symbol} ${playingAudioId === audio.id ? '停止播放' : '播放标准音'}`}
                    aria-pressed={playingAudioId === audio.id}
                    onClick={() => {
                      if (playingAudioId === audio.id) {
                        stopPlayback();
                        return;
                      }
                      stopPlayback();
                      setAudioFailureId(null);
                      const controller = new AbortController();
                      playback.current = { audioId: audio.id, controller };
                      setPlayingAudioId(audio.id);
                      void audioPlayer
                        .play(audio.id, controller.signal)
                        .catch((reason: unknown) => {
                          if (reason instanceof Error && reason.name !== 'AbortError')
                            setAudioFailureId(audio.id);
                        })
                        .finally(() => {
                          if (playback.current?.controller === controller) {
                            playback.current = null;
                            setPlayingAudioId(null);
                          }
                        });
                    }}
                  >
                    {playingAudioId === audio.id ? '■ 停止标准音' : '♫ 播放标准音'}
                  </button>
                ) : (
                  <button
                    className="audio-unavailable"
                    disabled
                    aria-label={`${item.symbol} 标准音待准备`}
                  >
                    ♫ 标准音待准备
                  </button>
                )}
                {audioFailureId === audio?.id && (
                  <p className="audio-error" role="alert">
                    标准音暂时无法播放，请检查家庭 Mac 上的音频资源。
                  </p>
                )}
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
  const [clockResolutionConfirm, setClockResolutionConfirm] = useState('');
  const [attemptHistory, setAttemptHistory] = useState<Record<string, AttemptHistoryPage>>({});
  const isParent = Boolean(boot.device?.isParent);
  const savedLessonExists = curriculum.lessons.some(
    (lesson: Lesson) => lesson.id === progress.selectedLessonId,
  );
  const selectedLessonChoice = lessonChoice || (savedLessonExists ? progress.selectedLessonId : '');
  async function loadAttemptHistory(knowledgeId: string, cursor?: string) {
    if (attemptHistory[knowledgeId]?.loading) return;
    const previous = attemptHistory[knowledgeId];
    setAttemptHistory((current) => ({
      ...current,
      [knowledgeId]: {
        items: previous?.items ?? [],
        nextCursor: previous?.nextCursor ?? null,
        loaded: previous?.loaded ?? false,
        loading: true,
        error: false,
      },
    }));
    const params = new URLSearchParams({ limit: '8' });
    if (cursor) params.set('cursor', cursor);
    try {
      const page = await api(
        `/profiles/knowledge/${encodeURIComponent(knowledgeId)}/attempts?${params.toString()}`,
      );
      setAttemptHistory((current) => {
        const prior = current[knowledgeId];
        return {
          ...current,
          [knowledgeId]: {
            items: cursor
              ? [...(prior?.items ?? []), ...(page.items as AttemptRecord[])]
              : (page.items as AttemptRecord[]),
            nextCursor: typeof page.nextCursor === 'string' ? page.nextCursor : null,
            loaded: true,
            loading: false,
            error: false,
          },
        };
      });
    } catch {
      setAttemptHistory((current) => ({
        ...current,
        [knowledgeId]: {
          items: current[knowledgeId]?.items ?? [],
          nextCursor: current[knowledgeId]?.nextCursor ?? null,
          loaded: current[knowledgeId]?.loaded ?? false,
          loading: false,
          error: true,
        },
      }));
    }
  }
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
            家庭进度修订号 {progress.revision} · {progress.attemptCount ?? 0} 次练习记录
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
      <section className="parent-progress" aria-labelledby="parent-progress-title">
        <h3 id="parent-progress-title">按知识点查看进度</h3>
        <p className="parent-progress-note">
          状态由 Mac
          根据最近练习记录计算；“独立答对”只统计首次作答且未用提示的客观题，不是考试成绩。
        </p>
        {curriculum.lessons.map((lesson: Lesson) => {
          const items = curriculum.knowledgeItems.filter(
            (item: Knowledge) => item.lessonId === lesson.id,
          );
          if (items.length === 0) return null;
          return (
            <details className="parent-lesson-progress" key={lesson.id}>
              <summary>
                {lesson.order}. {lesson.title}
              </summary>
              <ul>
                {items.map((item: Knowledge) => {
                  const state = progress.mastery.find(
                    (entry: Progress['mastery'][number]) => entry.knowledgeId === item.id,
                  );
                  const statusLabel =
                    state?.status === 'mastered'
                      ? '已掌握'
                      : state?.status === 'practicing'
                        ? '练习中'
                        : '未开始';
                  const requiredModes = (state?.requiredModes ?? [])
                    .map((mode: string) => exerciseModeLabels[mode])
                    .filter(Boolean);
                  const coveredModes = (state?.coveredModes ?? [])
                    .filter((mode: string) => state?.requiredModes?.includes(mode))
                    .map((mode: string) => exerciseModeLabels[mode])
                    .filter(Boolean);
                  const displayedAccuracy =
                    state?.sampleSize && state.accuracy !== null
                      ? Math.round(state.accuracy * 100)
                      : null;
                  const history = attemptHistory[item.id];
                  return (
                    <li key={item.id}>
                      <div className="parent-knowledge-title">
                        <strong>{item.symbol}</strong>
                        <span>{statusLabel}</span>
                        {state?.reviewDue && (
                          <span className="parent-due-label">
                            待复习{state.reviewDueDate ? ` · ${state.reviewDueDate}` : ''}
                          </span>
                        )}
                      </div>
                      <small>
                        {state && state.sampleSize > 0
                          ? `最近 ${state.sampleSize} 道有效练习：独立首次答对 ${state.correctCount} 题${displayedAccuracy === null ? '' : `（${displayedAccuracy}%）`}`
                          : `暂无有效练习记录${requiredModes.length ? ` · 需要练习：${requiredModes.join('、')}` : ''}`}
                      </small>
                      {state && state.sampleSize > 0 && (
                        <small>
                          独立答对覆盖：{coveredModes.length ? coveredModes.join('、') : '暂无'}；
                          本知识点要求：{requiredModes.length ? requiredModes.join('、') : '未配置'}
                        </small>
                      )}
                      <details
                        className="knowledge-attempt-history"
                        onToggle={(event) => {
                          if (event.currentTarget.open && !history?.loaded && !history?.loading)
                            void loadAttemptHistory(item.id);
                        }}
                      >
                        <summary>
                          查看练习记录
                          {history?.loaded ? `（已加载 ${history.items.length} 条）` : ''}
                        </summary>
                        {history?.loading && <p role="status">正在读取这项知识点的记录…</p>}
                        {history?.error && (
                          <div>
                            <p role="alert">暂时无法读取记录，请检查 Mac Studio 连接后重试。</p>
                            <button
                              className="quiet"
                              disabled={history.loading}
                              onClick={() =>
                                void loadAttemptHistory(item.id, history.nextCursor ?? undefined)
                              }
                            >
                              重试读取
                            </button>
                          </div>
                        )}
                        {history?.loaded && history.items.length === 0 && (
                          <p>这项知识点还没有练习记录。</p>
                        )}
                        {history && history.items.length > 0 && (
                          <ol>
                            {history.items.map((attempt: AttemptRecord) => (
                              <li key={attempt.id}>
                                <time dateTime={attempt.occurredAt}>
                                  {formatAttemptTime(attempt.occurredAt)}
                                </time>
                                <span>{exerciseModeLabels[attempt.mode] ?? '其他练习'}</span>
                                <span>{attemptOutcome(attempt)}</span>
                              </li>
                            ))}
                          </ol>
                        )}
                        {history?.nextCursor && (
                          <button
                            className="quiet"
                            disabled={history.loading}
                            onClick={() =>
                              void loadAttemptHistory(item.id, history.nextCursor ?? undefined)
                            }
                          >
                            显示更早记录
                          </button>
                        )}
                      </details>
                    </li>
                  );
                })}
              </ul>
            </details>
          );
        })}
      </section>
      <div className="parent-setting">
        <div>
          <strong>当前课程</strong>
          <p>
            {savedLessonExists
              ? '孩子只可学习当前课及之前内容。'
              : '已保存的课程不在此版本中；原有进度会保留，请重新选择学校当前课。'}
          </p>
        </div>
        <div className="inline-control">
          <select
            value={selectedLessonChoice}
            onChange={(event) => setLessonChoice(event.target.value)}
          >
            <option value="">请选择当前课程</option>
            {curriculum.lessons.map((lesson: Json) => (
              <option key={lesson.id} value={lesson.id}>
                {lesson.order}. {lesson.title}
              </option>
            ))}
          </select>
          <button
            className="quiet"
            disabled={!isParent || !selectedLessonChoice}
            onClick={() =>
              void act(async () => {
                await api('/household/current-lesson', {
                  method: 'PUT',
                  body: JSON.stringify({
                    lessonId: selectedLessonChoice,
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
      {(progress.clockSkewDetected || (progress.pendingClockAttempts ?? 0) > 0) && (
        <div className="parent-setting clock-pending-setting">
          <div>
            <strong>服务器时间与待校时练习</strong>
            <p>
              {progress.clockSkewDetected
                ? 'Mac Studio 时间比先前记录回退超过 5 分钟。请先校准系统时间；期间的新练习不会计入掌握度。'
                : '系统时间已恢复。请决定如何处理待校时练习；保留的记录始终不计入掌握度。'}
            </p>
            <p>待处理练习：{progress.pendingClockAttempts ?? 0} 条</p>
          </div>
          {(progress.pendingClockAttempts ?? 0) > 0 && !progress.clockSkewDetected && (
            <div className="clock-pending-actions">
              <label>
                输入处理方式确认
                <input
                  aria-label="确认处理待校时练习"
                  value={clockResolutionConfirm}
                  onChange={(event) => setClockResolutionConfirm(event.target.value)}
                />
              </label>
              <button
                className="quiet"
                disabled={!isParent || clockResolutionConfirm !== '保留为不计分练习' || busy}
                onClick={() =>
                  void act(async () => {
                    await api('/profiles/clock-pending/resolve', {
                      method: 'POST',
                      body: JSON.stringify({
                        resolution: 'keep-unscored',
                        confirmation: clockResolutionConfirm,
                      }),
                    });
                    setClockResolutionConfirm('');
                    await refresh();
                  })
                }
              >
                保留为不计分练习
              </button>
              <button
                className="danger-button"
                disabled={!isParent || clockResolutionConfirm !== '删除待校时练习' || busy}
                onClick={() =>
                  void act(async () => {
                    await api('/profiles/clock-pending/resolve', {
                      method: 'POST',
                      body: JSON.stringify({
                        resolution: 'discard',
                        confirmation: clockResolutionConfirm,
                      }),
                    });
                    setClockResolutionConfirm('');
                    await refresh();
                  })
                }
              >
                删除待校时练习
              </button>
            </div>
          )}
        </div>
      )}
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
              <p>
                这份 schema v{importPreview.migratedFromSchemaVersion}{' '}
                备份已显式迁移；旧备份没有待校时标记，历史练习按普通记录导入。
              </p>
            )}
            <p>
              将整体替换为 {importPreview.counts.attempts} 条练习、
              {importPreview.counts.sessions} 个会话、
              {importPreview.counts.skippedInstances} 道跳过题和
              {importPreview.counts.reviewPlans} 项复习计划；其中待校时练习{' '}
              {importPreview.counts.clockPendingAttempts ?? 0} 条。
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

function AdultConfirmDialog({
  open,
  onConfirm,
  onCancel,
}: {
  open: boolean;
  onConfirm: () => void;
  onCancel: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current;
    if (!element) return;
    if (open && !element.open) element.showModal();
    if (!open && element.open) element.close();
  }, [open]);

  return (
    <dialog
      className="adult-confirm-dialog"
      ref={dialog}
      aria-labelledby="adult-confirm-title"
      onCancel={(event) => {
        event.preventDefault();
        onCancel();
      }}
    >
      <span className="eyebrow">请家长接手</span>
      <h2 id="adult-confirm-title">这里是家庭管理区</h2>
      <p>
        这里会显示学习记录，并提供设备配对、备份和删除操作。请把设备交给家长再继续。
        这一步只用于防止孩子误触，不会代替家长权限验证。
      </p>
      <div className="adult-confirm-actions">
        <button className="quiet" onClick={onCancel}>
          返回孩子学习
        </button>
        <button autoFocus onClick={onConfirm}>
          我是家长，继续
        </button>
      </div>
    </dialog>
  );
}

function Notice({ error, onReconnect }: { error: string; onReconnect: () => void }) {
  const message =
    error === 'MAC_UNREACHABLE'
      ? '暂时无法连接家庭 Mac Studio，本次操作结果未确认。检查 Mac 和家庭局域网后，再点一次刚才的操作；答题会沿用原请求号，不会重复计分。'
      : `操作未完成：${error}。请检查本机服务连接后重试。`;
  return error ? (
    <div className="error-notice" role="alert">
      <p>{message}</p>
      {error === 'MAC_UNREACHABLE' && (
        <button className="quiet" onClick={onReconnect}>
          重新连接并恢复
        </button>
      )}
    </div>
  ) : null;
}
