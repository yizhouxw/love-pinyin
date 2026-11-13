import { useEffect, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import { gameCatalog } from '../domain/games';
import {
  advanceWorld,
  initialWorld,
  laneX,
  type Action,
  type GameSettings,
  type Scene,
  type World,
  type EngineConfig,
} from '../domain/scene-game';
import type { Answer, Exercise, Hint } from '../domain/learning-api';
import { GamePercussion } from '../platform/audio/game-percussion';
import { narration } from './labels';
import { VoiceButton, VoiceFailure, type useLearningVoice } from './learning-voice';
import { SceneWorld } from './scene-world';
import { Notice } from './notice';
import './scene-game.css';
import { compatibleRun, segmentAt, type GameRun } from '../domain/game-levels';
import { useGameInput } from './use-game-input';
import { useGamePointer } from './use-game-pointer';
import {
  readScenePreference,
  saveScenePreference,
  readSceneDisplay,
  saveSceneDisplay,
  type ScenePreference,
} from '../platform/game-preferences';

const motionPreference = () => window.matchMedia('(prefers-reduced-motion: reduce)');
const subscribeToMotion = (notify: () => void) => {
  const preference = motionPreference();
  preference.addEventListener('change', notify);
  return () => preference.removeEventListener('change', notify);
};
const prefersReducedMotion = () => motionPreference().matches;

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
  reducedMotion: boolean;
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
  const systemReducedMotion = useSyncExternalStore(subscribeToMotion, prefersReducedMotion);
  const staticChoices = systemReducedMotion || props.reducedMotion;
  const game = gameCatalog.games.find((g) => g.id === gameId)!;
  const scene = game.scene as Scene;
  const run = props.run?.level
    ? props.run
    : compatibleRun(
        gameId,
        Array.from({ length: props.total }, (_, i) => `legacy-${i}`),
      );
  const segment = segmentAt(run, props.index)!;
  const pattern = run.patterns[segment.patternId]!;
  const stageRef = useRef<HTMLDivElement>(null);
  const staticRef = useRef<HTMLDivElement>(null);
  const priorMode = useRef(staticChoices);
  useLayoutEffect(() => {
    if (priorMode.current !== staticChoices) {
      priorMode.current = staticChoices;
      (staticChoices ? staticRef.current : stageRef.current)?.focus({ preventScroll: true });
    }
  }, [staticChoices]);
  const nextRef = useRef(props.onNext);
  const [display, setDisplay] = useState(() => readSceneDisplay(gameId, props.reducedMotion));
  const { enlarged, assist } = display;
  function changeDisplay(value: Partial<typeof display>) {
    setDisplay((prior) => ({ ...prior, ...value }));
  }
  useEffect(() => {
    saveSceneDisplay(gameId, display);
  }, [gameId, display]);
  const helpDialog = useRef<HTMLDialogElement>(null);
  const settingsDialog = useRef<HTMLDialogElement>(null);
  const settingsButton = useRef<HTMLButtonElement>(null);
  const wasPaused = useRef(false);
  const [draft, setDraft] = useState(() => readScenePreference(gameId));
  const [applying, setApplying] = useState(false);
  const [settingsError, setSettingsError] = useState('');
  useEffect(() => {
    nextRef.current = props.onNext;
  }, [props.onNext]);
  useEffect(() => {
    window.scrollTo({ top: 0, behavior: 'instant' });
    stageRef.current?.focus({ preventScroll: true });
  }, []);
  const level = props.settings?.level ?? 'gentle',
    speed = props.settings?.speed ?? 'slow';
  const config: EngineConfig = {
    pattern,
    count: question.options.length,
    ...gameCatalog.levels[level],
    speedFactor:
      gameCatalog.speeds[speed].factor *
      (1 + (run.level.number - 1) * gameCatalog.play.levelSpeedStep),
  };
  const seed = () => ({
    ...initialWorld(),
    x: laneX(Math.floor(question.options.length / 2), question.options.length),
    hit: props.pendingOptionId
      ? Math.max(
          0,
          question.options.findIndex((o) => o.id === props.pendingOptionId),
        )
      : null,
  });
  const [frames] = useState(() => {
    let frame = { world: seed(), backdrop: 0 };
    const listeners = new Set<() => void>();
    return {
      read: () => frame,
      write(world: World, backdrop = frame.backdrop) {
        frame = { world, backdrop };
        listeners.forEach((listener) => listener());
      },
      subscribe(listener: () => void) {
        listeners.add(listener);
        return () => listeners.delete(listener);
      },
    };
  });
  const [hit, setHit] = useState<number | null>(() => frames.read().world.hit);
  const taskId = useRef(props.taskId);
  const submitted = useRef<number | null>(null);
  const [replaying, setReplaying] = useState(false);
  const [resolvedHit, setResolvedHit] = useState(false);
  useLayoutEffect(() => {
    if (taskId.current === props.taskId) return;
    const { world: prior, backdrop } = frames.read();
    const next = {
      ...initialWorld(),
      x: prior.x,
      vx: prior.vx,
      time: prior.time,
      jump: prior.jump,
      jumpVelocity: prior.jumpVelocity,
      forwardVelocity: prior.forwardVelocity,
      flash: 0.25,
    };
    taskId.current = props.taskId;
    submitted.current = null;
    frames.write(next, backdrop + prior.distance);
    setHit(null);
    setResolvedHit(false);
    setReplaying(false);
  }, [frames, props.taskId]);
  const [paused, setPaused] = useState(false);
  const physics = {
    ...config,
    assist: assist || config.assist,
    speedFactor: config.speedFactor * (assist ? 0.45 : 1),
  };
  const engine = useRef(physics);
  useEffect(() => {
    engine.current = physics;
  });
  const [sfx, setSfx] = useState(true);
  const percussion = useRef<GamePercussion | null>(null);
  const [sending, setSending] = useState(false);
  const callback = useRef(props.onAnswer);
  useEffect(() => {
    callback.current = props.onAnswer;
  }, [props.onAnswer]);
  const done = Boolean(answer && (answer.correct || corrected));
  const stopped =
    paused ||
    applying ||
    locked ||
    busy ||
    sending ||
    !!voice.playingId ||
    done ||
    Boolean(answer && !replaying);
  useEffect(() => {
    percussion.current = new GamePercussion();
    return () => {
      percussion.current?.close();
      percussion.current = null;
    };
  }, []);
  const canMove = !staticChoices && !paused && !applying && (!answer || done || replaying);
  const canMovePastTarget = useRef(false);
  useLayoutEffect(() => {
    canMovePastTarget.current = !stopped;
  }, [stopped]);
  useEffect(() => {
    if (!canMove) {
      percussion.current?.close();
      return;
    }
    let frame = 0;
    let last = 0;
    function tick(time: number) {
      const dt = last ? (time - last) / 1000 : 0;
      last = time;
      const { world, backdrop } = frames.read();
      const config = engine.current;
      if (!document.hidden && dt > 0) {
        if (world.hit !== null) {
          frames.write(world, backdrop + Math.min(dt, 0.05) * config.travel * config.speedFactor);
        } else {
          const next = advanceWorld(world, dt, config, undefined, canMovePastTarget.current);
          frames.write(next);
          if (next.hit !== null) setHit(next.hit);
        }
      }
      frame = requestAnimationFrame(tick);
    }
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [canMove, frames]);
  useEffect(() => {
    if (stopped || hit === null || submitted.current === hit) return;
    submitted.current = hit;
    setSending(true);
    void callback.current(question.options[hit]!.id).finally(() => {
      setResolvedHit(true);
      setSending(false);
    });
  }, [hit, question.options, stopped]);
  useEffect(() => {
    const hide = () => {
      if (document.hidden) {
        setPaused(true);
        percussion.current?.close();
      }
    };
    document.addEventListener('visibilitychange', hide);
    return () => document.removeEventListener('visibilitychange', hide);
  }, []);
  function fire(action: Action) {
    const { world } = frames.read();
    if (staticChoices || stopped || world.hit !== null) return;
    if (sfx && scene === 'drum' && action === 'act') percussion.current?.hit();
    const next = advanceWorld(world, 0, engine.current, action);
    frames.write(next);
    if (next.hit !== null) setHit(next.hit);
  }
  function focusStage() {
    stageRef.current?.focus({ preventScroll: true });
  }
  function togglePause() {
    voice.stop();
    if (!paused && props.onPause) props.onPause();
    else setPaused((value) => !value);
  }
  const pointer = useGamePointer(!staticChoices && !stopped && hit === null, scene, fire);
  useGameInput({
    enabled: !staticChoices && !stopped && hit === null,
    scene,
    onAction: fire,
    onPause: togglePause,
    focus: focusStage,
  });
  useEffect(() => {
    if (busy || sending || voice.playingId || paused || props.error) return;
    if (done) {
      nextRef.current();
    } else if (answer && hit !== null && resolvedHit) {
      const frame = requestAnimationFrame(() => {
        const { world, backdrop } = frames.read();
        const distance = scene === 'space' ? pattern.choiceAt : pattern.choiceAt - 65;
        submitted.current = null;
        frames.write(
          { ...world, distance, hit: null, shot: null, note: 0, forwardVelocity: 0 },
          backdrop + world.distance - distance,
        );
        setHit(null);
        setResolvedHit(false);
        setReplaying(true);
      });
      return () => cancelAnimationFrame(frame);
    }
  }, [
    answer,
    busy,
    done,
    frames,
    hit,
    pattern.choiceAt,
    paused,
    props.error,
    resolvedHit,
    scene,
    sending,
    voice.playingId,
  ]);
  const cue = narration.exercises[question.id];
  const controls =
    scene === 'runner'
      ? ['← 换道', '跳跃 ↑', '换道 →']
      : scene === 'boat'
        ? ['左桨 ↶', '双桨前进', '右桨 ↷']
        : scene === 'drum'
          ? ['放过音符', '咚！击鼓', '放过音符']
          : ['← 瞄准', '发射 ↑', '瞄准 →'];
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
        <button className="quiet" onClick={togglePause}>
          {paused ? '▶ 继续' : 'Ⅱ 暂停'}
        </button>
        <button
          className="quiet"
          disabled={staticChoices}
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
        <p>{game.controls} 方向键 / A、D，空格 / W；P 暂停。</p>
        <p>
          {run.level.title} · {run.level.chapters[segment.chapterIndex]?.title}
        </p>
        <div className="scene-voices">
          <VoiceButton id={game.voiceId} voice={voice} label="听玩法" />
          <VoiceButton id={run.level.voiceId} voice={voice} label="听本关故事" />
          <VoiceButton id={`prompt-${question.id}`} voice={voice} label="听题目说明" />
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
          {staticChoices ? (
            <div
              ref={staticRef}
              tabIndex={-1}
              className="scene-controls"
              role="group"
              aria-label="直接选择拼音"
            >
              {question.options.map((option, index) => (
                <button
                  key={option.id}
                  disabled={stopped || hit !== null}
                  aria-describedby={
                    option.id === (answer?.correctOptionId ?? hint?.answer.optionId)
                      ? 'static-correct-target'
                      : undefined
                  }
                  className={
                    option.id === (answer?.correctOptionId ?? hint?.answer.optionId)
                      ? 'scene-action'
                      : ''
                  }
                  onClick={() => {
                    const { world } = frames.read();
                    frames.write({ ...world, hit: index });
                    setHit(index);
                  }}
                >
                  {option.label}
                </button>
              ))}
              <span id="static-correct-target" className="screen-reader-only">
                提示：正确目标
              </span>
            </div>
          ) : (
            <>
              <LiveScene
                frames={frames}
                stageRef={stageRef}
                scene={scene}
                physics={physics}
                run={run}
                question={question}
                highlight={answer?.correctOptionId ?? hint?.answer.optionId}
                paused={paused}
                onResume={() => setPaused(false)}
              />
              <div className="scene-controls" role="group" aria-label="场景动作">
                {controls.map((label, i) => (
                  <button
                    key={i}
                    disabled={stopped || hit !== null}
                    className={i === 1 ? 'scene-action' : ''}
                    aria-label={label}
                    {...pointer(
                      scene === 'drum' && i !== 1
                        ? 'pass'
                        : i === 0
                          ? 'left'
                          : i === 1
                            ? 'act'
                            : 'right',
                    )}
                  >
                    {label}
                  </button>
                ))}
              </div>
              <div className="scene-tools">
                <button
                  className="quiet"
                  aria-pressed={assist}
                  onClick={() => changeDisplay({ assist: !assist })}
                >
                  🐢 辅助慢动作{assist ? '：开' : '：关'}
                </button>
                {scene === 'drum' && (
                  <button className="quiet" aria-pressed={sfx} onClick={() => setSfx(!sfx)}>
                    鼓声{sfx ? '：开' : '：关'}
                  </button>
                )}
              </div>
            </>
          )}
        </section>
        <aside className="scene-mission" aria-label="本关任务">
          <h1>{cue?.text ?? question.prompt}</h1>
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

type FrameSource = {
  read: () => { world: World; backdrop: number };
  subscribe: (listener: () => void) => () => void;
};

function LiveScene({
  frames,
  stageRef,
  scene,
  physics,
  run,
  question,
  highlight,
  paused,
  onResume,
}: {
  frames: FrameSource;
  stageRef: React.Ref<HTMLDivElement>;
  scene: Scene;
  physics: EngineConfig;
  run: GameRun;
  question: Exercise;
  highlight?: string;
  paused: boolean;
  onResume: () => void;
}) {
  const { world, backdrop } = useSyncExternalStore(frames.subscribe, frames.read);
  return (
    <div
      ref={stageRef}
      className="scene-stage"
      tabIndex={0}
      role="group"
      aria-label="游戏操作区：方向键控制，空格行动"
      data-scene={scene}
      data-task-id={question.id}
      data-speed-factor={physics.speedFactor}
      data-world-x={world.x}
      data-world-vx={world.vx}
      data-world-strokes={world.strokes}
      data-option-count={question.options.length}
      data-world-distance={world.distance}
      data-world-hit={world.hit ?? ''}
      data-choice-at={physics.pattern.choiceAt}
      data-pattern-id={physics.pattern.id}
      data-world-jump={world.jump}
      data-motor-misses={world.misses}
    >
      <SceneWorld
        scene={scene}
        world={world}
        options={question.options}
        config={physics}
        theme={run.theme}
        scenery={run.level.number}
        routeOffset={backdrop}
        highlight={highlight}
      />
      {world.misses > 0 && world.hit === null && (
        <p className="scene-motor-note">刚才没有碰到目标，继续试试。</p>
      )}
      {paused && (
        <div className="scene-curtain">
          <strong>先停一停</strong>
          <button onClick={onResume}>▶ 继续游戏</button>
        </div>
      )}
    </div>
  );
}
