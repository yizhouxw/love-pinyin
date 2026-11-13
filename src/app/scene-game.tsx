import { useEffect, useRef, useState } from 'react';
import { gameCatalog } from '../domain/games';
import type { GameSettings, Scene } from '../domain/scene-game';
import type { Answer, Exercise, Hint } from '../domain/learning-api';
import { narration } from './labels';
import { VoiceButton, VoiceFailure, type useLearningVoice } from './learning-voice';
import { AdventureStage } from './adventure-stage';
import { Notice } from './notice';
import './scene-game.css';
import { compatibleRun, segmentAt, type GameRun } from '../domain/game-levels';
import {
  readScenePreference,
  saveScenePreference,
  readSceneDisplay,
  saveSceneDisplay,
  type ScenePreference,
} from '../platform/game-preferences';
type Props = {
  gameId: string;
  taskId: string;
  settings?: GameSettings;
  run?: GameRun;
  question: Exercise;
  index: number;
  total: number;
  voice: ReturnType<typeof useLearningVoice>;
  busy: boolean;
  locked: boolean;
  error: string;
  answer: Answer | null;
  hint: Hint | null;
  corrected: boolean;
  pendingOptionId?: string;
  onInteract: () => void;
  onAnswer: (id: string) => Promise<void>;
  onHint: () => void;
  onSkip: () => void;
  onNext: () => void;
  onExit: () => void;
  onPause?: () => void;
  onSettings: (preference: ScenePreference) => Promise<void>;
};
export function SceneGame(props: Props) {
  const { gameId, question, voice, busy, locked, answer, hint, corrected } = props;
  const game = gameCatalog.games.find((g) => g.id === gameId)!;
  const scene = game.scene as Scene;
  const run = props.run?.level
    ? props.run
    : compatibleRun(
        gameId,
        Array.from({ length: props.total }, (_, i) => `legacy-${i}`),
      );
  const segment = segmentAt(run, props.index)!;
  const [display, setDisplay] = useState(() => readSceneDisplay(gameId));
  const { enlarged, assist } = display;
  function changeDisplay(value: Partial<typeof display>) {
    setDisplay((prior) => ({ ...prior, ...value }));
  }
  useEffect(() => {
    saveSceneDisplay(gameId, display);
  }, [gameId, display]);
  const helpDialog = useRef<HTMLDialogElement>(null),
    settingsDialog = useRef<HTMLDialogElement>(null),
    settingsButton = useRef<HTMLButtonElement>(null);
  const wasPaused = useRef(false);
  const [draft, setDraft] = useState(() => readScenePreference(gameId));
  const [draftAssist, setDraftAssist] = useState(assist);
  const [applying, setApplying] = useState(false),
    [settingsError, setSettingsError] = useState('');
  const [started, setStarted] = useState(false);
  const [paused, setPaused] = useState(false),
    [sending, setSending] = useState(false);
  const [selection, setSelection] = useState<{ task: string; index: number | null }>(() => ({
    task: props.taskId,
    index: props.pendingOptionId
      ? question.options.findIndex((o) => o.id === props.pendingOptionId)
      : null,
  }));
  const hit = selection.task === props.taskId ? selection.index : null;
  const [retry, setRetry] = useState('');
  const [attempt, setAttempt] = useState(0);
  const [celebrated, setCelebrated] = useState(false);
  const nextRef = useRef(props.onNext);
  useEffect(() => {
    nextRef.current = props.onNext;
  }, [props.onNext]);
  const level = props.settings?.level ?? 'gentle',
    speed = props.settings?.speed ?? 'slow';
  const done = Boolean(answer && (answer.correct || corrected));
  const stopped =
    !started ||
    paused ||
    applying ||
    locked ||
    busy ||
    sending ||
    !!voice.playingId ||
    done ||
    Boolean(answer && retry !== props.taskId);
  const choosing = useRef(false);
  function choose(index: number) {
    if (stopped || choosing.current || hit !== null) return;
    choosing.current = true;
    setSelection({ task: props.taskId, index });
    setSending(true);
    setCelebrated(false);
    void props.onAnswer(question.options[index]!.id).finally(() => {
      choosing.current = false;
      setSending(false);
    });
  }
  useEffect(() => {
    if (!started || busy || sending || voice.playingId || paused || props.error) return;
    if (done && (scene !== 'drum' || celebrated)) {
      const timer = window.setTimeout(() => nextRef.current(), 850);
      return () => window.clearTimeout(timer);
    }
    if (answer && !done && hit !== null) {
      const timer = window.setTimeout(() => {
        setSelection({ task: props.taskId, index: null });
        setRetry(props.taskId);
        setAttempt((n) => n + 1);
      }, 400);
      return () => window.clearTimeout(timer);
    }
  }, [
    started,
    answer,
    busy,
    sending,
    voice.playingId,
    paused,
    props.error,
    done,
    scene,
    celebrated,
    hit,
    props.taskId,
  ]);
  useEffect(() => {
    const hide = () => {
      if (document.hidden) {
        setPaused(true);
        voice.stop();
      }
    };
    document.addEventListener('visibilitychange', hide);
    return () => document.removeEventListener('visibilitychange', hide);
  }, [voice]);
  function focusStage() {
    document.querySelector<HTMLElement>('.adventure-canvas')?.focus({ preventScroll: true });
  }
  function togglePause() {
    if (!started) return;
    voice.stop();
    if (!paused && props.onPause) props.onPause();
    else setPaused((value) => !value);
  }
  const cue = narration.exercises[question.id];
  const hitOption = hit === null ? null : question.options[hit];
  return (
    <main
      className={`scene-page scene-${scene}${enlarged ? ' scene-enlarged' : ''}`}
      onClickCapture={(event) => {
        props.onInteract();
        const target = event.target;
        if (
          event.detail > 0 &&
          target instanceof HTMLElement &&
          target.closest('.scene-controls,.scene-voices,.scene-tools')
        )
          queueMicrotask(() => {
            if (!settingsDialog.current?.open && !helpDialog.current?.open) focusStage();
          });
      }}
    >
      <nav className="scene-nav">
        <button className="quiet" disabled={busy || sending} onClick={props.onExit}>
          ← 保存并退出游戏
        </button>
        <strong>
          {game.icon} {game.title}
        </strong>
        <span>
          {run.level.chapters[segment.chapterIndex]?.title} · 任务 {props.index + 1} / {props.total}
        </span>
      </nav>
      <div className="scene-view-actions">
        <button className="quiet" disabled={!started} onClick={togglePause}>
          {paused ? '▶ 继续' : 'Ⅱ 暂停'}
        </button>
        <button
          className="quiet"
          disabled={false}
          aria-pressed={enlarged}
          onClick={() => changeDisplay({ enlarged: !enlarged })}
        >
          {enlarged ? '↙ 还原画面' : '↗ 放大画面'}
        </button>
        <button
          ref={settingsButton}
          className="quiet"
          onClick={() => {
            voice.stop();
            wasPaused.current = paused;
            setPaused(true);
            setSettingsError('');
            setDraftAssist(assist);
            setDraft({
              ...readScenePreference(gameId),
              difficulty: props.settings?.requestedDifficulty ?? 'auto',
              speed: props.settings?.requestedSpeed ?? 'auto',
            });
            settingsDialog.current?.showModal();
          }}
        >
          ⚙ 游戏设置
        </button>
      </div>
      <dialog
        ref={settingsDialog}
        className="scene-settings"
        aria-labelledby="scene-settings-title"
        onCancel={(event) => {
          if (applying) event.preventDefault();
        }}
        onClose={() => {
          setPaused(wasPaused.current);
          settingsButton.current?.focus();
        }}
      >
        <form
          onSubmit={(event) => {
            event.preventDefault();
            if (applying) return;
            setApplying(true);
            setSettingsError('');
            void props
              .onSettings(draft)
              .then(() => {
                saveScenePreference(gameId, draft);
                changeDisplay({ assist: draftAssist });
                settingsDialog.current?.close();
              })
              .catch((reason: Error) => setSettingsError(reason.message))
              .finally(() => setApplying(false));
          }}
        >
          <span className="eyebrow">按自己的节奏玩</span>
          <h2 id="scene-settings-title">游戏设置</h2>
          <p>难度和速度应用到当前关；不会改变拼音题目和已答记录。</p>
          <div className="game-preferences">
            <label>
              本关难度
              <select
                aria-label="本关难度"
                disabled={applying}
                value={draft.difficulty}
                onChange={(e) =>
                  setDraft({
                    ...draft,
                    difficulty: e.target.value as ScenePreference['difficulty'],
                  })
                }
              >
                <option value="auto">按进度匹配</option>
                {Object.entries(gameCatalog.levels).map(([key, value]) => (
                  <option key={key} value={key}>
                    {value.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              本关速度
              <select
                aria-label="本关速度"
                disabled={applying}
                value={draft.speed}
                onChange={(e) =>
                  setDraft({ ...draft, speed: e.target.value as ScenePreference['speed'] })
                }
              >
                <option value="auto">自动</option>
                {Object.entries(gameCatalog.speeds).map(([key, value]) => (
                  <option key={key} value={key}>
                    {value.label}
                  </option>
                ))}
              </select>
            </label>
            <label>
              下次开局题量
              <select
                aria-label="下次开局题量"
                disabled={applying}
                value={draft.taskCount}
                onChange={(e) => setDraft({ ...draft, taskCount: Number(e.target.value) })}
              >
                {Array.from(
                  { length: gameCatalog.play.maxTasks - gameCatalog.play.minTasks + 1 },
                  (_, i) => gameCatalog.play.minTasks + i,
                ).map((n) => (
                  <option key={n} value={n}>
                    {n} 个拼音
                  </option>
                ))}
              </select>
            </label>
          </div>
          {scene === 'runner' && (
            <label className="scene-wait-setting">
              <input
                type="checkbox"
                checked={draftAssist}
                disabled={applying}
                onChange={(event) => setDraftAssist(event.target.checked)}
              />{' '}
              经过果树时减速（启蒙难度始终开启）
            </label>
          )}
          <p className="adult-hint">
            本关共 {props.total} 题，已完成 {props.index} 题。题量在下次开始关卡时生效。
          </p>
          <Notice error={settingsError} onReconnect={() => setSettingsError('')} />
          <div className="scene-settings-actions">
            <button
              type="button"
              className="quiet"
              disabled={applying}
              onClick={() => settingsDialog.current?.close()}
            >
              取消
            </button>
            <button type="submit" disabled={applying}>
              {applying ? '正在保存…' : '应用设置'}
            </button>
          </div>
        </form>
      </dialog>
      <dialog
        ref={helpDialog}
        className="scene-settings"
        aria-labelledby="scene-help-title"
        onClose={() => {
          voice.stop();
          setPaused(wasPaused.current);
        }}
      >
        <h2 id="scene-help-title">玩法与故事</h2>
        <p>{game.controls} 可用 Tab 选择场景目标，回车行动；P 暂停。</p>
        <p>
          {run.level.title} · {run.level.chapters[segment.chapterIndex]?.title}
        </p>
        <div className="scene-voices">
          <VoiceButton id={game.voiceId} voice={voice} label="听玩法" />
          <VoiceButton id={run.level.voiceId} voice={voice} label="听本关故事" />
        </div>
        <button className="quiet" onClick={() => helpDialog.current?.close()}>
          关闭
        </button>
      </dialog>
      <div className="scene-layout">
        <section className="scene-playfield" aria-label={game.title}>
          <div className="scene-quick-audio scene-voices">
            <VoiceButton
              id={question.audioRef ?? `prompt-${question.id}`}
              kind={question.audioRef ? 'standard' : 'private'}
              voice={voice}
              label={question.audioRef ? '听拼音' : '听题目'}
              alwaysReplay
            />
            <button
              className="quiet"
              onClick={() => {
                wasPaused.current = paused;
                setPaused(true);
                helpDialog.current?.showModal();
              }}
            >
              玩法与故事
            </button>
            <progress aria-label="关卡完成进度" value={props.index} max={props.total} />
          </div>
          <AdventureStage
            key={`${props.taskId}:${attempt}:${level}`}
            scene={scene}
            options={question.options}
            disabled={stopped || hit !== null}
            paused={paused}
            started={started}
            onStart={() => {
              setStarted(true);
              setPaused(false);
              if (question.audioRef) voice.playStandard(question.audioRef);
              else voice.play(`prompt-${question.id}`);
              focusStage();
            }}
            assist={assist || gameCatalog.levels[level].assist}
            speed={
              gameCatalog.speeds[speed].factor *
              (gameCatalog.levels[level].travel / 100) *
              (1 + (run.level.number - 1) * gameCatalog.play.levelSpeedStep)
            }
            difficulty={level}
            index={props.index}
            highlight={answer?.correctOptionId ?? hint?.answer.optionId}
            done={done}
            rhythmEnabled={!busy && !sending && !voice.playingId && !applying}
            onChoose={choose}
            onFinished={() => setCelebrated(true)}
            onResume={() => {
              setPaused(false);
              focusStage();
            }}
            onPause={togglePause}
          />
        </section>
        <aside className="scene-mission" aria-label="本关任务">
          <h1>{game.controls}</h1>
          {cue?.visualCue && <div className="scene-cue">{cue.visualCue}</div>}
          <div className="scene-help">
            <button
              className="quiet"
              disabled={busy || sending || hit !== null}
              onClick={props.onHint}
            >
              听提示
            </button>
            {voice.failureId && locked && (
              <button className="quiet" disabled={busy || sending} onClick={props.onSkip}>
                先跳过这题
              </button>
            )}
          </div>
          <div className="scene-response" aria-label="本关反馈">
            <VoiceFailure voice={voice} />
            {hit !== null && !answer && !busy && !sending && props.error && (
              <button
                className="quiet"
                onClick={() => hitOption && void props.onAnswer(hitOption.id)}
              >
                重试保存这次选择
              </button>
            )}
            {answer && !done && (
              <p className="scene-hint" role="status">
                再试一次，亮起的是正确目标。
              </p>
            )}
            {hint && !answer && (
              <p className="scene-hint" role="status">
                {hint.explanation}
              </p>
            )}
            <Notice
              error={props.error}
              onReconnect={() => {
                if (hitOption) void props.onAnswer(hitOption.id);
              }}
            />
          </div>
        </aside>
      </div>
    </main>
  );
}
