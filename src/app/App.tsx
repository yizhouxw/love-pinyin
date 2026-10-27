import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import playback from '../../content/playback.json';
import type {
  Answer,
  Bootstrap,
  Curriculum,
  Hint,
  Json,
  Option,
  Progress,
  Session,
} from '../domain/learning-api';
import { isGuest, leaveGuest } from '../platform/guest';
import {
  readGuidancePreference,
  resolveGuidance,
  saveGuidancePreference,
} from '../platform/guidance-preference';
import { api } from '../platform/api-client';
import {
  readPlaybackPreference,
  resolvePlaybackGap,
  savePlaybackPreference,
} from '../platform/playback-preference';
import {
  clearPendingAnswer,
  idempotencyKey,
  readPendingAnswer,
  replayPendingAnswer,
  savePendingAnswer,
} from '../platform/pending-answer';
import { DailyReadingPage } from './daily-reading';
import { gameCatalog } from '../domain/games';
import { GameZone, GamePause } from './game-zone';
import { SceneGame } from './scene-game';
import { readScenePreference } from '../platform/game-preferences';
import { useGameClock } from './use-game-clock';
import { GameOptionContent } from './game-option-content';
import { GuestPanel } from './guest-panel';
import { GuidanceSwitch } from './guidance-switch';
import { Picture } from './illustrations';
import { narration } from './labels';
import { useLearningVoice, VoiceButton, VoiceFailure, type LearningAudio } from './learning-voice';
import { LessonDetail } from './lesson-detail';
import { LessonNavigation } from './lesson-navigation';
import { AdultConfirmDialog } from './management-controls';
import { Notice } from './notice';
import { PairingManagement } from './pairing-management';
import { PairingPage } from './pairing-page';
import { ParentPanel } from './parent-panel';
import { SessionSummary } from './session-summary';
import { ReleaseHistory } from './release-history';
import './styles.css';

export function App() {
  const [household, setHousehold] = useState<Bootstrap | null>(null);
  return (
    <>
      {isGuest() && (
        <aside className="guest-banner" aria-label="访客模式">
          <span>
            <strong>访客体验</strong> · 本次进度暂存
          </span>
          <button className="quiet" onClick={leaveGuest}>
            清除并退出访客
          </button>
        </aside>
      )}
      {!isGuest() && household?.paired && (
        <aside className="guest-banner family-banner" aria-label="家庭模式">
          <span>
            <strong>家庭学习</strong> · 进度已连接家庭 Mac
          </span>
        </aside>
      )}
      <LearningApp onBootstrap={setHousehold} />
    </>
  );
}

export function LearningApp({ onBootstrap }: { onBootstrap: (value: Bootstrap) => void }) {
  const [boot, setBoot] = useState<Bootstrap | null>(null);
  useEffect(() => {
    if (boot && !boot.guest) onBootstrap(boot);
  }, [boot, onBootstrap]);
  const [curriculum, setCurriculum] = useState<Curriculum | null>(null);
  const [progress, setProgress] = useState<Progress | null>(null);
  const [guidancePreference, setGuidancePreference] = useState(readGuidancePreference);
  const [playbackPreference, setPlaybackPreference] = useState(() =>
    readPlaybackPreference(isGuest()),
  );
  const familyGap = progress?.settings.playbackGapSeconds ?? playback.gap.defaultSeconds;
  const gapSeconds = resolvePlaybackGap(familyGap, playbackPreference);
  function changePlaybackGap(seconds: number) {
    const preference = { seconds, familyDefault: familyGap };
    setPlaybackPreference(preference);
    savePlaybackPreference(preference, isGuest());
  }
  const familyGuidance = progress?.settings.soundEnabled !== false;
  const guidanceEnabled = resolveGuidance(familyGuidance, guidancePreference);
  function changeGuidance(enabled: boolean) {
    const preference = { enabled, familyDefault: familyGuidance };
    setGuidancePreference(preference);
    saveGuidancePreference(preference);
  }
  const [session, setSession] = useState<Session | null>(null);
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [hint, setHint] = useState<Hint | null>(null);
  const [answer, setAnswer] = useState<Answer | null>(null);
  const [pictureStatus, setPictureStatus] = useState<Record<string, boolean>>({});
  const [pictureRetry, setPictureRetry] = useState(0);
  const [correctedInstance, setCorrectedInstance] = useState<string | null>(null);
  const [blendDraft, setBlendDraft] = useState<{ instanceId: string; optionId: string } | null>(
    null,
  );
  const blendConfirm = useRef<HTMLButtonElement | null>(null);
  const blendOptions = useRef(new Map<string, HTMLButtonElement>());
  const [gamesOpen, setGamesOpen] = useState(window.location.hash === '#games');
  const [dailyOpen, setDailyOpen] = useState(window.location.hash === '#daily-reading');
  useEffect(() => {
    const followHash = () => {
      setDailyOpen(window.location.hash === '#daily-reading');
      setGamesOpen(window.location.hash === '#games');
    };
    window.addEventListener('hashchange', followHash);
    return () => window.removeEventListener('hashchange', followHash);
  }, []);
  const [parentOpen, setParentOpen] = useState(false);
  const [parentGateOpen, setParentGateOpen] = useState(false);
  const [lessonChoice, setLessonChoice] = useState('');
  const [lessonViewId, setLessonViewId] = useState<string | null>(null);
  const lessonFromCatalogue = useRef(false);
  const previousLessonView = useRef<string | null>(null);
  function openLesson(id: string, fromCatalogue = false) {
    lessonFromCatalogue.current = fromCatalogue;
    setLessonViewId(id);
  }
  useEffect(() => {
    if (lessonViewId) {
      window.scrollTo({ top: 0, behavior: 'instant' });
      document.getElementById(`lesson-heading-${lessonViewId}`)?.focus({ preventScroll: true });
    } else if (previousLessonView.current) {
      if (lessonFromCatalogue.current) {
        const catalogue = document.querySelector<HTMLDetailsElement>('.course-browser');
        if (catalogue) catalogue.open = true;
        document
          .querySelector<HTMLButtonElement>(`[data-lesson-id="${previousLessonView.current}"]`)
          ?.focus();
      } else document.querySelector<HTMLButtonElement>('.listen-lesson-button')?.focus();
    }
    previousLessonView.current = lessonViewId;
  }, [lessonViewId]);
  const [learningAudio, setLearningAudio] = useState<LearningAudio | null>(null);
  const voiceStarted = useRef(false);

  useEffect(() => {
    document.documentElement.dataset.reducedMotion = String(
      Boolean(progress?.settings?.reducedMotion),
    );
  }, [progress?.settings?.reducedMotion]);

  const refresh = useCallback(async () => {
    const state = (await api('/bootstrap')) as Bootstrap;
    if (!state.paired) {
      setBoot(state);
      return;
    }
    const [course, stats, current, sounds] = await Promise.all([
      api('/curriculum'),
      api('/profiles/progress'),
      api('/sessions/current'),
      api('/learning-audio').catch(() => null),
    ]);
    setLearningAudio(sounds as LearningAudio | null);
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
    // Reveal the next screen only with its matching progress revision and settings.
    setBoot(state);
  }, []);

  useEffect(() => {
    let cancelled = false;
    void api('/bootstrap')
      .then(async (result) => {
        const state = result as Bootstrap;
        if (cancelled) return;
        setBoot(state);
        if (!state.paired) return;
        const [course, stats, current, sounds] = await Promise.all([
          api('/curriculum'),
          api('/profiles/progress'),
          api('/sessions/current'),
          api('/learning-audio').catch(() => null),
        ]);
        if (cancelled) return;
        setLearningAudio(sounds as LearningAudio | null);
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
          ['listen-choice', 'symbol-choice', 'tone-choice', 'blend-choice'].includes(exercise.type),
      ),
    ),
  );
  const mastery = progress?.mastery ?? [];
  const masteryById = new Map(mastery.map((item) => [item.knowledgeId, item]));
  const active = session;
  const taskIndex = active
    ? active.tasks.findIndex((task: Json) => !active.results?.[task.instanceId])
    : -1;
  const task = active && taskIndex >= 0 ? active.tasks[taskIndex] : null;
  const voice = useLearningVoice(task?.instanceId ?? null);
  const { play: playVoice, playSequence, stop: stopVoice } = voice;
  const gameClock = useGameClock(
    Boolean(active?.gameId) && (boot?.profile?.roundsSinceBreak ?? 0) < 2,
    stopVoice,
  );
  const game = gameCatalog.games.find((item) => item.id === active?.gameId);
  const question = task?.exercise;
  const pictureIds = [
    ...new Set(
      [question?.pictureId, ...(question?.options.map((o) => o.pictureId) ?? [])].filter(
        (id): id is string => Boolean(id),
      ),
    ),
  ];
  const pictureScope = `${task?.instanceId ?? ''}/${pictureRetry}`;
  const picturesPending = pictureIds.some((id) => pictureStatus[`${pictureScope}/${id}`] !== true);
  const picturesFailed = pictureIds.some((id) => pictureStatus[`${pictureScope}/${id}`] === false);
  function onPictureStatus(id: string, ready: boolean) {
    setPictureStatus((prior) => ({ ...prior, [`${pictureScope}/${id}`]: ready }));
  }
  const blendPreview =
    question?.type === 'blend-choice' && task?.instanceId === blendDraft?.instanceId
      ? question.options.find((option: Option) => option.id === blendDraft?.optionId)
      : undefined;
  useEffect(() => {
    if (blendPreview) blendConfirm.current?.focus();
  }, [blendPreview, task?.instanceId]);
  useEffect(() => {
    if (task?.instanceId) window.scrollTo({ top: 0, behavior: 'instant' });
  }, [task?.instanceId]);
  const corrected = Boolean(task && correctedInstance === task.instanceId);
  const questionVoice = question ? narration.exercises[question.id] : undefined;
  const standardHeard = !question?.audioRef || voice.completedIds.has(question.audioRef);
  const currentVoiceFailed = Boolean(question?.audioRef && voice.failedIds.has(question.audioRef));
  const answerNeedsAudio = Boolean(question && (currentVoiceFailed || !standardHeard));
  const answerUnavailableReason =
    answer && (answer.correct || corrected)
      ? '这题已经完成，点“继续”进入下一题。'
      : busy
        ? '正在连接家庭 Mac、保存练习，请稍等。'
        : picturesPending
          ? picturesFailed
            ? '答案暂时不能选：图片未加载好，请点“重试图片”。'
            : '正在准备图片，请稍等。'
          : currentVoiceFailed
            ? '答案暂时不能选：拼音声音未播放成功，请重新点“听拼音”，也可以先跳过。'
            : !standardHeard
              ? voice.playingId === question?.audioRef
                ? '请听一听，听完就能选。'
                : '点“听拼音”，听完就能选。'
              : null;
  const autoVoiceId =
    !boot?.paired || parentOpen || parentGateOpen || lessonViewId
      ? null
      : gameClock.paused
        ? gameClock.reason.includes('LIMIT')
          ? 'ui-game_rest'
          : null
        : (boot.profile?.roundsSinceBreak ?? 0) >= 2
          ? 'ui-rest'
          : active && !question
            ? 'ui-summary'
            : question && answer
              ? answer.correct || corrected
                ? active?.gameId
                  ? 'ui-game_checkpoint'
                  : 'ui-correct'
                : (answer.explanationAudioId ?? 'ui-incorrect')
              : question && hint
                ? `hint-${question.id}`
                : question
                  ? `prompt-${question.id}`
                  : null;

  const autoStandardId =
    question && !answer && !hint && !gameClock.paused ? question.audioRef : undefined;
  useEffect(() => {
    if (autoVoiceId && voiceStarted.current && autoStandardId) {
      playSequence([
        ...(guidanceEnabled && !active?.gameId
          ? [{ id: autoVoiceId, kind: 'private' as const, optional: true }]
          : []),
        { id: autoStandardId, kind: 'standard' },
      ]);
    } else if (autoVoiceId && voiceStarted.current && guidanceEnabled) playVoice(autoVoiceId);
    else stopVoice();
    return stopVoice;
  }, [
    autoVoiceId,
    autoStandardId,
    active?.gameId,
    playSequence,
    playVoice,
    stopVoice,
    guidanceEnabled,
    lessonViewId,
    parentOpen,
    parentGateOpen,
    boot?.paired,
    gameClock.paused,
  ]);

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

  async function beginLesson(lessonId: string, gameId?: string, gameLevelId?: string) {
    voiceStarted.current = true;
    if (guidanceEnabled && !gameId) playVoice('ui-start');
    else stopVoice();
    const started = (await api('/sessions', {
      method: 'POST',
      body: JSON.stringify({
        lessonId,
        ...(gameId
          ? {
              gameId,
              gameLevelId,
              gameDifficulty: readScenePreference(gameId).difficulty,
              gameSpeed: readScenePreference(gameId).speed,
              gameTaskCount: readScenePreference(gameId).taskCount,
            }
          : {}),
      }),
    })) as Session;
    setSession(started);
    setBlendDraft(null);
    setAnswer(null);
    setHint(null);
  }

  async function beginReview(knowledgeId: string) {
    voiceStarted.current = true;
    if (guidanceEnabled) playVoice('ui-start');
    const started = (await api(`/reviews/${encodeURIComponent(knowledgeId)}/sessions`, {
      method: 'POST',
      body: JSON.stringify({}),
    })) as Session;
    setSession(started);
    setBlendDraft(null);
    setAnswer(null);
    setHint(null);
  }

  async function submitOption(optionId: string) {
    if (
      !task ||
      busy ||
      answerNeedsAudio ||
      gameClock.paused ||
      picturesPending ||
      (answer && (answer.correct || corrected))
    )
      return;
    await act(async () => {
      if (answer) {
        if (optionId === answer.correctOptionId) setCorrectedInstance(task.instanceId);
        else playVoice(answer.explanationAudioId ?? 'ui-incorrect');
        setBlendDraft(null);
        return;
      }
      let pending = readPendingAnswer(task.instanceId);
      if (pending && pending.answerOptionId !== optionId)
        throw new Error('上一题提交结果待确认，请再点一次原来的答案以安全重试。');
      if (!pending) {
        pending = { requestId: idempotencyKey(), answerOptionId: optionId };
        savePendingAnswer(task.instanceId, pending);
      }
      const result = (await api(`/instances/${task.instanceId}/answer`, {
        method: 'POST',
        body: JSON.stringify(pending),
      })) as Omit<Answer, 'selectedOptionId'>;
      clearPendingAnswer(task.instanceId);
      setBlendDraft(null);
      setAnswer({ ...result, selectedOptionId: pending.answerOptionId });
      await refreshProgressOnly();
    });
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
    return <PairingPage boot={boot} busy={busy} act={act} refresh={refresh} error={error} />;

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
          <VoiceButton id="ui-rest" voice={voice} label="听休息提醒" />
          <VoiceFailure voice={voice} />
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

  const title =
    (active?.reviewKnowledgeId
      ? '两题复习'
      : active
        ? lessonById.get(active.lessonId ?? '')?.title
        : undefined) ?? currentLesson?.title;

  async function exitGame() {
    if (!active) return;
    stopVoice();
    gameClock.pause('');
    await api(`/sessions/${active.id}/finish`, { method: 'POST' });
    await api('/games/pause', { method: 'POST' });
    setSession(null);
    setBlendDraft(null);
    setAnswer(null);
    setHint(null);
    setGamesOpen(true);
    window.location.hash = 'games';
    await refresh();
  }

  if (active?.gameId && gameClock.paused)
    return (
      <GamePause
        reason={gameClock.reason}
        voice={voice}
        busy={busy}
        onResume={() => {
          voiceStarted.current = true;
          void gameClock.resume();
        }}
        onExit={() => void act(exitGame)}
      />
    );

  if (active?.gameId && game && question && task)
    return (
      <SceneGame
        key={task.instanceId}
        gameId={game.id}
        settings={active.gameSettings}
        run={active.gameRun}
        question={question}
        index={taskIndex}
        total={active.tasks.length}
        voice={voice}
        busy={busy}
        locked={answerNeedsAudio}
        error={error}
        answer={answer}
        hint={hint}
        corrected={corrected}
        reducedMotion={progress?.settings.reducedMotion ?? false}
        pendingOptionId={readPendingAnswer(task.instanceId)?.answerOptionId}
        onInteract={() => {
          voiceStarted.current = true;
        }}
        onAnswer={submitOption}
        onSettings={async (preference) => {
          const controller = new AbortController();
          const timer = window.setTimeout(
            () => controller.abort(),
            gameCatalog.policy.requestTimeoutSeconds * 1000,
          );
          try {
            const saved = await api(`/sessions/${active.id}/game-settings`, {
              method: 'PATCH',
              signal: controller.signal,
              body: JSON.stringify({ difficulty: preference.difficulty, speed: preference.speed }),
            });
            setSession((current) =>
              current?.id === active.id
                ? {
                    ...current,
                    gameSettings: saved as unknown as import('../domain/scene-game').GameSettings,
                  }
                : current,
            );
          } finally {
            window.clearTimeout(timer);
          }
        }}
        onExit={() => void act(exitGame)}
        onNext={() =>
          void act(async () => {
            stopVoice();
            setSession((await api('/sessions/current')) as Session);
            setAnswer(null);
            setHint(null);
            setBlendDraft(null);
          })
        }
        onHint={() =>
          void act(async () => {
            const data = await api(`/instances/${task.instanceId}/hint`, { method: 'POST' });
            setHint(data as Hint);
          })
        }
        onSkip={() =>
          void act(async () => {
            stopVoice();
            await api(`/instances/${task.instanceId}/skip`, { method: 'POST' });
            setSession((await api('/sessions/current')) as Session);
            setAnswer(null);
            setHint(null);
            setBlendDraft(null);
          })
        }
      />
    );

  if (active && question)
    return (
      <main
        className={`play-page ${game ? `game-play game-${game.id}` : ''}`}
        onClickCapture={() => {
          voiceStarted.current = true;
        }}
      >
        <nav className="play-nav">
          <button
            className="icon-button"
            aria-label="退出练习"
            disabled={busy}
            onClick={() =>
              void act(async () => {
                if (active.gameId) {
                  await exitGame();
                  return;
                }
                stopVoice();
                await api(`/sessions/${active.id}/finish`, { method: 'POST' });
                setSession(null);
                setBlendDraft(null);
                setAnswer(null);
                setHint(null);
                await refresh();
              })
            }
          >
            ←
          </button>
          <div>
            <small>{game ? `${game.icon} ${game.title}` : `拼音小岛 · ${title}`}</small>
            <strong>
              第 {taskIndex + 1} / {active.tasks.length} 关
            </strong>
          </div>
          <GuidanceSwitch enabled={guidanceEnabled} onChange={changeGuidance} />
          <span className="progress-dots">
            {active.tasks.map((_: Json, i: number) => (
              <i key={i} className={i < taskIndex ? 'done' : i === taskIndex ? 'now' : ''} />
            ))}
          </span>
        </nav>
        {game && (
          <aside className="game-trail" aria-label="本关探索进度">
            <span>
              {game.icon} {game.title}
            </span>
            <div aria-hidden="true">
              {active.tasks.map((_, index) => (
                <span key={index} className={index < taskIndex ? 'collected' : ''}>
                  {index < taskIndex ? '🌱' : '○'}
                </span>
              ))}
            </div>
            <small>完成就点亮 · 不比快慢 · 随时休息</small>
          </aside>
        )}
        {!active.gameId && !active.reviewKnowledgeId && active.tasks.length < 6 && (
          <p className="session-size-note" role="status">
            本课目前准备了 {active.tasks.length} 道可用练习，本轮先完成这些。
          </p>
        )}
        <section className="question-card">
          <p className="eyebrow">
            {question.pictureId || question.options.some((o) => o.pictureId)
              ? '生活拼音站'
              : question.type === 'listen-choice'
                ? '听音发现站'
                : question.type === 'tone-choice'
                  ? question.audioRef
                    ? '声调听辨站'
                    : '声调观察站'
                  : question.type === 'blend-choice'
                    ? '拼读组合站'
                    : '字形发现站'}
          </p>
          {question.pictureId && (
            <div className="word-question-picture">
              <Picture
                key={pictureScope}
                id={question.pictureId}
                catalog={curriculum?.illustrations}
                retry={pictureRetry}
                onStatus={(ready) => onPictureStatus(question.pictureId!, ready)}
              />
            </div>
          )}
          {questionVoice?.visualCue && (
            <div className="question-cue" aria-label="观察目标">
              {questionVoice.visualCue}
            </div>
          )}
          <h1>{questionVoice?.text ?? question.prompt}</h1>
          <div className="question-audio-actions" role="group" aria-label="听题与示范音">
            {question.audioRef ? (
              <>
                <VoiceButton
                  id={question.audioRef}
                  kind="standard"
                  voice={voice}
                  label="听拼音"
                  className="listen-question"
                />
                <details className="question-help">
                  <summary>听题目说明</summary>
                  <VoiceButton id={`prompt-${question.id}`} voice={voice} label="听题目" />
                </details>
              </>
            ) : (
              <VoiceButton
                id={`prompt-${question.id}`}
                voice={voice}
                label="听题目"
                className="listen-question"
              />
            )}
          </div>
          <p id="answer-availability" className="listen-before-answer" role="status">
            {answerUnavailableReason ?? '可以选择答案了。'}
          </p>
          <VoiceFailure voice={voice} />
          {picturesPending && (
            <div className="picture-failure" role="status">
              <p>{picturesFailed ? '图片暂时没加载好，可以重试。' : '图片正在加载，请稍等。'}</p>
              <button className="quiet" onClick={() => setPictureRetry((n) => n + 1)}>
                ↻ 重试图片
              </button>
              <VoiceButton id="picture-error" voice={voice} label="听图片提示" />
            </div>
          )}
          <div
            className={`options ${question.type === 'blend-choice' ? 'blend-options' : ''}`}
            role="group"
            aria-label={question.type === 'blend-choice' ? '完整拼读候选' : '选择答案'}
          >
            {question.options.map((option: Json, index: number) => (
              <div className="option-with-voice" key={option.id}>
                <button
                  data-option-id={option.id}
                  aria-describedby="answer-availability"
                  className={`option game-option ${question.type} ${hint?.answer.optionId === option.id && !answer ? 'hinted' : ''} ${answer ? (option.id === answer.correctOptionId ? 'correct' : option.id === answer.selectedOptionId ? 'wrong' : '') : ''}`}
                  disabled={
                    Boolean(answer && (answer.correct || corrected)) ||
                    busy ||
                    answerNeedsAudio ||
                    picturesPending
                  }
                  ref={
                    question.type === 'blend-choice'
                      ? (element) => {
                          if (element) blendOptions.current.set(option.id, element);
                          else blendOptions.current.delete(option.id);
                        }
                      : undefined
                  }
                  aria-pressed={
                    question.type === 'blend-choice' ? blendPreview?.id === option.id : undefined
                  }
                  onClick={() => {
                    if (question.type === 'blend-choice') {
                      setBlendDraft({ instanceId: task.instanceId, optionId: option.id });
                      if (guidanceEnabled) playVoice('ui-blend_ready');
                    } else void submitOption(option.id);
                  }}
                >
                  <span className="option-index">{String.fromCharCode(65 + index)}</span>
                  <GameOptionContent
                    pictureId={option.pictureId}
                    pictureKey={pictureScope}
                    pictureRetry={pictureRetry}
                    onPictureStatus={onPictureStatus}
                    illustrations={curriculum?.illustrations}
                    writing={option.writing}
                    writingCatalog={curriculum?.writing}
                    type={question.type}
                    label={option.label}
                    initials={curriculum?.inventory?.initials ?? []}
                  />
                </button>
                {questionVoice?.options[option.id] && (
                  <VoiceButton
                    id={`option-${question.id}-${option.id}`}
                    voice={voice}
                    label={`听选项 ${String.fromCharCode(65 + index)}`}
                    className="option-voice"
                  />
                )}
              </div>
            ))}
          </div>
          {question.type === 'blend-choice' && (
            <section className="blend-workbench" aria-label="拼读试选台">
              <VoiceButton id="ui-blend_how" voice={voice} label="听拼读怎么玩" />
              {blendPreview ? (
                <>
                  <div className="blend-preview" aria-label="当前拼读预览">
                    <span aria-hidden="true">🧩</span>
                    <strong>{blendPreview.label}</strong>
                  </div>
                  <div className="blend-controls">
                    <button
                      ref={blendConfirm}
                      className="blend-confirm"
                      aria-label="确认拼读"
                      aria-describedby="answer-availability"
                      disabled={
                        busy ||
                        answerNeedsAudio ||
                        picturesPending ||
                        Boolean(answer && (answer.correct || corrected))
                      }
                      onClick={() => void submitOption(blendPreview.id)}
                    >
                      ✓ 确认拼读
                    </button>
                    <button
                      className="quiet"
                      aria-label="撤销拼读选择"
                      disabled={busy}
                      onClick={() => {
                        const id = blendPreview.id;
                        setBlendDraft(null);
                        stopVoice();
                        blendOptions.current.get(id)?.focus();
                      }}
                    >
                      ↶ 重新选择
                    </button>
                  </div>
                </>
              ) : (
                <p className="blend-empty">🧩 选一张卡片，看看拼在一起的样子</p>
              )}
            </section>
          )}
          <div className="exercise-response">
            {answer && (
              <div className={`feedback ${answer.correct ? 'good' : 'try-again'}`} role="status">
                <strong>
                  {answer.correct
                    ? '答对啦！'
                    : corrected
                      ? '找到正确答案啦！'
                      : '没关系，看看亮起来的卡片，再选一次。'}
                </strong>
                <span>
                  {answer.clockPending
                    ? '此练习已保存为待校时记录，不计入掌握度。'
                    : answer.mastery.status === 'mastered'
                      ? '这个知识点已掌握 ✨'
                      : '完成后继续下一关吧。'}
                </span>
                {answer.explanation && answer.explanationAudioId && (
                  <details className="answer-explanation">
                    <summary>听讲解</summary>
                    <p>{answer.explanation}</p>
                    <VoiceButton id={answer.explanationAudioId} voice={voice} label="重听讲解" />
                  </details>
                )}
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
                        (await api(`/instances/${task.instanceId}/hint`, {
                          method: 'POST',
                        })) as Hint,
                      ),
                    )
                  }
                >
                  💡 给我一点提示
                </button>
                <button
                  className="quiet skip-button"
                  disabled={busy}
                  onClick={() =>
                    void act(async () => {
                      stopVoice();
                      await api(`/instances/${task.instanceId}/skip`, { method: 'POST' });
                      const nextSession = (await api('/sessions/current')) as Session;
                      setHint(null);
                      setBlendDraft(null);
                      setSession(nextSession);
                    })
                  }
                >
                  ↷ 先跳过这题
                </button>
              </div>
            )}
            {hint && !answer && (
              <div className="hint-box">
                <span>{hint.explanation}</span>
                <VoiceButton id={`hint-${question.id}`} voice={voice} label="听提示" />
              </div>
            )}
            {answer && (
              <button
                className="next-button"
                disabled={busy}
                onClick={() =>
                  void act(async () => {
                    stopVoice();
                    const nextSession = (await api('/sessions/current')) as Session;
                    setAnswer(null);
                    setHint(null);
                    setSession(nextSession);
                  })
                }
              >
                继续 →
              </button>
            )}
          </div>
        </section>
        <Notice error={error} onReconnect={() => void act(refresh)} />
      </main>
    );
  if (active && taskIndex < 0)
    return (
      <SessionSummary
        session={active}
        voice={voice}
        busy={busy}
        error={error}
        onReconnect={() => void act(refresh)}
        onFinish={() =>
          void act(async () => {
            if (active.gameId) {
              await exitGame();
              return;
            }
            await api(`/sessions/${active.id}/finish`, { method: 'POST' });
            setSession(null);
            await refresh();
          })
        }
      />
    );

  async function refreshProgressOnly() {
    setProgress((await api('/profiles/progress')) as Progress);
  }

  if (gamesOpen && !parentOpen && curriculum && progress)
    return (
      <main className="home-page">
        <GameZone
          guidanceEnabled={guidanceEnabled}
          onGuidanceChange={changeGuidance}
          curriculum={curriculum}
          lessonId={progress.selectedLessonId}
          voice={voice}
          busy={busy}
          onBack={() => {
            stopVoice();
            window.location.hash = '';
            setGamesOpen(false);
          }}
          onStart={(gameId, gameLevelId) =>
            void act(() => beginLesson(progress.selectedLessonId, gameId, gameLevelId))
          }
        />
        <Notice error={error} onReconnect={() => void act(refresh)} />
      </main>
    );

  if (dailyOpen)
    return (
      <main className="home-page">
        <DailyReadingPage
          gapSeconds={gapSeconds}
          onGapChange={changePlaybackGap}
          guidanceEnabled={guidanceEnabled}
          onGuidanceChange={changeGuidance}
          onBack={() => {
            window.location.hash = '';
            setDailyOpen(false);
          }}
        />
        <ReleaseHistory contentVersion={curriculum?.contentVersion} />
      </main>
    );

  return (
    <main className="home-page">
      <header className="topbar">
        {(!lessonViewId || parentOpen) && (
          <GuidanceSwitch enabled={guidanceEnabled} onChange={changeGuidance} />
        )}
        <div className="brand">
          <span className="brand-mark">拼</span>
          <span>爱拼音</span>
        </div>
        {boot.isLocalHost && (
          <button
            className="parent-button"
            onClick={() => {
              if (parentOpen) setParentOpen(false);
              else setParentGateOpen(true);
            }}
          >
            {parentOpen ? '返回学习' : '家长管理'}
          </button>
        )}
      </header>
      <AdultConfirmDialog
        open={Boolean(boot.isLocalHost && parentGateOpen)}
        onConfirm={() => {
          setParentGateOpen(false);
          setParentOpen(true);
        }}
        onCancel={() => setParentGateOpen(false)}
      />
      {progress && curriculum && (
        <>
          {(!lessonViewId || parentOpen) && (
            <section className={`welcome ${parentOpen ? 'parent-welcome' : 'learning-welcome'}`}>
              <div>
                <p className="eyebrow">
                  {parentOpen ? (boot.guest ? '访客学习空间' : '家庭学习空间') : '每天一点，慢慢学'}
                </p>
                <h1>{parentOpen ? '家长管理' : <>今天学拼音</>}</h1>
                {parentOpen ? (
                  <p>
                    {boot.device?.label} · {boot.guest ? '临时学习设置' : '家庭学习设置'}
                  </p>
                ) : (
                  <h2 className="current-course">
                    {currentLesson
                      ? `第 ${currentLesson.order} 课 · ${currentLesson.title}`
                      : '请选择当前课'}
                  </h2>
                )}
                {!parentOpen && (
                  <>
                    {!currentLesson && (
                      <p className="current-course-help">
                        保存的当前课不在此课程版本中。已有学习记录会保留，请家长重新选择学校正在学习的课程。
                      </p>
                    )}
                    <div className="start-actions">
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
                        <span aria-hidden="true">▶</span>
                      </button>
                      <button
                        className="listen-lesson-button"
                        disabled={!currentLesson || busy}
                        onClick={() => currentLesson && openLesson(currentLesson.id)}
                      >
                        课堂学习 <span aria-hidden="true">→</span>
                      </button>
                    </div>
                    <details className="home-help">
                      <summary>第一次玩？听听玩法</summary>
                      <VoiceButton id="ui-welcome" voice={voice} label="听怎么玩" />
                    </details>
                    <VoiceFailure voice={voice} />
                  </>
                )}
              </div>
            </section>
          )}
          {!parentOpen && progress.clockSkewDetected && (
            <div className="error-notice" role="alert">
              Mac Studio
              时间似乎回退了。练习仍可继续，但新记录暂不计入掌握度；请家长检查服务器时间。
            </div>
          )}
          {parentOpen && !/^(BACKUP_|IMPORT_)/.test(error) && (
            <Notice error={error} onReconnect={() => void act(refresh)} />
          )}
          {parentOpen ? (
            boot.guest ? (
              <GuestPanel
                curriculum={curriculum}
                progress={progress}
                lessonChoice={lessonChoice}
                setLessonChoice={setLessonChoice}
                busy={busy}
                refresh={refresh}
                act={act}
              />
            ) : (
              <ParentPanel
                boot={boot}
                error={error}
                curriculum={curriculum}
                progress={progress}
                lessonChoice={lessonChoice}
                setLessonChoice={setLessonChoice}
                busy={busy}
                refresh={refresh}
                act={act}
                learningAudio={learningAudio}
                onGuidanceChange={changeGuidance}
              />
            )
          ) : lessonViewId ? (
            <LessonDetail
              key={lessonViewId}
              lesson={lessonById.get(lessonViewId)}
              knowledge={
                curriculum?.knowledgeItems.filter((item) => item.lessonId === lessonViewId) ?? []
              }
              audioRequirements={curriculum?.audioRequirements ?? []}
              familyAudio={learningAudio?.lessons[lessonViewId]}
              illustrations={curriculum?.illustrations}
              writingCatalog={curriculum?.writing}
              soundEnabled={guidanceEnabled}
              onGuidanceChange={changeGuidance}
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
                        ['listen-choice', 'symbol-choice', 'tone-choice', 'blend-choice'].includes(
                          exercise.type,
                        ),
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
              <section className="daily-entry games-entry">
                <div>
                  <span className="eyebrow">边玩边学 · 每次短一点</span>
                  <h2>拼音游戏乐园</h2>
                  <p>{gameCatalog.games.map((item) => item.title).join('、')}。</p>
                </div>
                <button
                  onClick={() => {
                    stopVoice();
                    voiceStarted.current = true;
                    window.location.hash = 'games';
                    setGamesOpen(true);
                    if (guidanceEnabled) playVoice('ui-game_welcome');
                  }}
                >
                  进入游戏乐园 →
                </button>
              </section>
              <section className="daily-entry">
                <div>
                  <span className="eyebrow">每天读一点</span>
                  <h2>天天练拼音</h2>
                  <p>听一听，跟着读。</p>
                </div>
                <button
                  onClick={() => {
                    stopVoice();
                    window.location.hash = 'daily-reading';
                    setDailyOpen(true);
                  }}
                >
                  进入天天练拼音 →
                </button>
              </section>
              <details className="course-browser">
                <summary>查看全部课程</summary>
                <LessonNavigation
                  lessons={lessons}
                  currentLesson={currentLesson}
                  masteryById={masteryById}
                  onSelect={(id) => openLesson(id, true)}
                />
              </details>
              <details className="home-progress-note">
                <summary>我的拼音花园 · {progress.completedSessions} 片叶子</summary>
                <span role="img" aria-label={`拼音花园已长出 ${progress.completedSessions} 片叶子`}>
                  🌱 {progress.completedSessions} 片叶子
                </span>
                <p>每完成一轮长出一片叶子。可以随时休息。</p>
              </details>
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
            </>
          )}
          {parentOpen && (
            <details className="management-section">
              <summary>连接其他设备</summary>
              <PairingManagement />
            </details>
          )}
          {!parentOpen && (
            <footer>
              <ReleaseHistory contentVersion={curriculum?.contentVersion} />
            </footer>
          )}
        </>
      )}
      {!parentOpen && <Notice error={error} onReconnect={() => void act(refresh)} />}
    </main>
  );
}
