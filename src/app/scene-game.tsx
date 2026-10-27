import { useEffect, useRef, useState } from 'react';
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

type Props = {
  gameId: string;
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
  const pattern = run.patterns[segment.patternId]!;
  const stageRef = useRef<HTMLDivElement>(null);
  const nextRef = useRef(props.onNext);
  const [display, setDisplay] = useState(() => readSceneDisplay(gameId, props.reducedMotion));
  const { enlarged, assist, autoContinue } = display;
  function changeDisplay(value: Partial<typeof display>) {
    setDisplay((prior) => ({ ...prior, ...value }));
  }
  useEffect(() => {
    saveSceneDisplay(gameId, display);
  }, [gameId, display]);
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
  const [world, setWorld] = useState<World>(seed);
  const current = useRef(world);
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
  const submitted = useRef<number | null>(null);
  const [replaying, setReplaying] = useState(false);
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
  useEffect(() => {
    if (stopped) {
      percussion.current?.close();
      return;
    }
    let frame = 0,
      last = 0;
    const tick = (time: number) => {
      if (document.hidden) {
        last = 0;
        frame = requestAnimationFrame(tick);
        return;
      }
      const dt = last ? (time - last) / 1000 : 0;
      last = time;
      const next = advanceWorld(current.current, dt, engine.current);
      current.current = next;
      setWorld(next);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [stopped]);
  useEffect(() => {
    if (
      locked ||
      busy ||
      paused ||
      voice.playingId ||
      world.hit === null ||
      submitted.current === world.hit
    )
      return;
    submitted.current = world.hit;
    setSending(true);
    void callback.current(question.options[world.hit]!.id).finally(() => setSending(false));
  }, [world.hit, question.options, locked, busy, paused, voice.playingId]);
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
    if (stopped || current.current.hit !== null) return;
    if (sfx && scene === 'drum' && action === 'act') percussion.current?.hit();
    const next = advanceWorld(current.current, 0, engine.current, action);
    current.current = next;
    setWorld(next);
  }
  function focusStage() {
    stageRef.current?.focus({ preventScroll: true });
  }
  function togglePause() {
    voice.stop();
    setPaused((value) => !value);
  }
  const pointer = useGamePointer(!stopped && world.hit === null, scene, fire);
  useGameInput({
    enabled: !stopped && world.hit === null,
    scene,
    onAction: fire,
    onPause: togglePause,
    focus: focusStage,
  });
  useEffect(() => {
    if (!done || busy || sending || voice.playingId || paused || props.error || !autoContinue)
      return;
    const timer = window.setTimeout(() => nextRef.current(), gameCatalog.play.continueMilliseconds);
    return () => window.clearTimeout(timer);
  }, [done, busy, sending, voice.playingId, paused, props.error, autoContinue]);
  function reset() {
    submitted.current = null;
    const next = seed();
    current.current = next;
    setWorld(next);
    setReplaying(true);
  }
  const cue = narration.exercises[question.id];
  const controls =
    scene === 'runner'
      ? ['← 换道', '跳跃 ↑', '换道 →']
      : scene === 'boat'
        ? ['左桨 ↶', '双桨前进', '右桨 ↷']
        : scene === 'drum'
          ? ['放过音符', '咚！击鼓', '放过音符']
          : ['← 瞄准', '发射 ↑', '瞄准 →'];
  const hitOption = world.hit === null ? null : question.options[world.hit];
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
            if (!settingsDialog.current?.open) focusStage();
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
          {run.level.title} · 任务 {props.index + 1} / {props.total}
        </span>
      </nav>
      <div className="scene-view-actions">
        <button
          className="quiet"
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
      <div className="level-journey" aria-label="完整关卡路线">
        {run.level.chapters.map((chapter, i) => (
          <span
            key={chapter.id}
            className={
              i === segment.chapterIndex ? 'active' : i < segment.chapterIndex ? 'finished' : ''
            }
          >
            {i < segment.chapterIndex ? '✓' : i + 1} {chapter.title}
          </span>
        ))}
        <progress aria-label="关卡完成进度" value={props.index} max={props.total} />
      </div>
      {!props.run?.level && (
        <p className="adult-hint">这是旧版未完成旅程；退出后可选择新的完整关卡。</p>
      )}
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
            <VoiceButton id={game.voiceId} voice={voice} label="听玩法" />
          </div>
          <div className="scene-topline">
            <span>
              {gameCatalog.levels[level].label} · {gameCatalog.speeds[speed].label} · 第{' '}
              {run.level.number} 关
            </span>
            <span>
              {scene === 'drum'
                ? `热身鼓点 ${world.beatHits.length} / ${pattern.beats.length}`
                : `沿途收集 ${world.collected.length} / ${pattern.pickups.length}`}{' '}
              · {Math.min(100, Math.round((world.distance / pattern.length) * 100))}%
            </span>
          </div>
          <div
            ref={stageRef}
            className="scene-stage"
            tabIndex={0}
            role="group"
            aria-label="游戏操作区：方向键控制，空格行动"
            data-scene={scene}
            data-speed-factor={physics.speedFactor}
            data-world-x={world.x}
            data-world-vx={world.vx}
            data-world-strokes={world.strokes}
            data-option-count={question.options.length}
            data-world-distance={world.distance}
            data-world-hit={world.hit ?? ''}
            data-choice-at={pattern.choiceAt}
            data-pattern-id={pattern.id}
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
              routeOffset={run.level.chapters
                .flatMap((c) => c.segments)
                .slice(0, props.index)
                .reduce((sum, s) => sum + run.patterns[s.patternId]!.length, 0)}
              highlight={answer?.correctOptionId ?? hint?.answer.optionId}
            />
            {paused && (
              <div className="scene-curtain">
                <strong>先停一停</strong>
                <button onClick={() => setPaused(false)}>▶ 继续游戏</button>
              </div>
            )}
          </div>
          <div className="scene-controls" role="group" aria-label="场景动作">
            {controls.map((label, i) => (
              <button
                key={i}
                disabled={stopped || world.hit !== null}
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
            <button className="quiet" onClick={togglePause}>
              {paused ? '▶ 继续' : 'Ⅱ 暂停'}
            </button>
            <button
              className="quiet"
              aria-pressed={assist}
              onClick={() => changeDisplay({ assist: !assist })}
            >
              🐢 辅助慢动作{assist ? '：开' : '：关'}
            </button>
            <button
              className="quiet"
              aria-pressed={autoContinue}
              onClick={() => changeDisplay({ autoContinue: !autoContinue })}
            >
              连续旅程：{autoContinue ? '开' : '关'}
            </button>
            {scene === 'drum' && (
              <button className="quiet" aria-pressed={sfx} onClick={() => setSfx(!sfx)}>
                鼓声{sfx ? '：开' : '：关'}
              </button>
            )}
          </div>
          <details className="scene-instructions">
            <summary>操作说明与键盘</summary>
            <p className="scene-instruction">
              {game.controls} 方向键 / A、D，空格 / W；P 暂停。
              <br />
              本段沿途有{pattern.obstacles.length}处障碍，{pattern.pickups.length}份补给
              {scene === 'drum' ? `，${pattern.beats.length}个热身鼓点` : ''}
              ；前方还有新的拼音任务。
            </p>
          </details>
          <p className="scene-motor-note" role="status">
            {scene === 'runner' && physics.assist && world.distance >= pattern.choiceAt - 65
              ? '选好拼音跑道，再按跳跃穿门。'
              : world.misses > 0
                ? '刚才没有碰到目标，继续试试，不算拼音答错。'
                : level === 'gentle' || assist
                  ? '启蒙与辅助模式会等你准备好，随时可以暂停。'
                  : '方向键控制，空格行动；想慢一点可打开辅助。'}
          </p>
        </section>
        <aside className="scene-mission" aria-label="本关任务">
          <span className="eyebrow">听清楚，再出发</span>
          <h1>{cue?.text ?? question.prompt}</h1>
          {cue?.visualCue && <div className="scene-cue">{cue.visualCue}</div>}
          <div className="scene-voices">
            <details className="scene-more-voices">
              <summary>故事与说明</summary>
              <VoiceButton id={run.level.voiceId} voice={voice} label="听本关故事" />
              <VoiceButton id={`prompt-${question.id}`} voice={voice} label="听题目说明" />
            </details>
          </div>
          <VoiceFailure voice={voice} />
          <p role="status" className="scene-audio-status">
            {locked
              ? '先听完拼音声音，再操作。'
              : voice.playingId
                ? '正在听声音，场景等一等。'
                : paused
                  ? '游戏已暂停。'
                  : '可以出发啦！'}
          </p>
          {world.hit !== null && !answer && (
            <div className="scene-arrival" role="status">
              <strong>已抵达 {hitOption?.label}</strong>
              <p>{busy || sending ? '正在保存这次选择…' : '保存结果待确认，请重试。'}</p>
              {!busy && !sending && (
                <button
                  onClick={() => {
                    if (hitOption) {
                      setSending(true);
                      void props.onAnswer(hitOption.id).finally(() => setSending(false));
                    }
                  }}
                >
                  重试保存这次选择
                </button>
              )}
            </div>
          )}
          {answer && (
            <div className={`feedback ${done ? 'good' : 'try-again'}`} role="status">
              <strong>
                {answer.correct
                  ? '送达成功，拼音答对啦！'
                  : corrected
                    ? '找到正确目标啦！'
                    : '这个拼音再听一听，亮起的是正确目标。'}
              </strong>
              <p>
                {answer.clockPending
                  ? '记录待校时，不计入掌握度。'
                  : '只保留首次作答，场景练习不会覆盖首次结果。'}
              </p>
              {answer.explanationAudioId && (
                <VoiceButton id={answer.explanationAudioId} voice={voice} label="听讲解" />
              )}
              {!done && (
                <button disabled={busy || sending} onClick={reset}>
                  ↻ 再走一次这段场景
                </button>
              )}
            </div>
          )}
          {hint && !answer && (
            <p className="scene-hint" role="status">
              {hint.explanation}
            </p>
          )}
          {done && autoContinue && (
            <p className="scene-auto-note">这一站已保存，听完反馈继续旅程。按 P 可停留。</p>
          )}
          {done ? (
            <button className="scene-next" disabled={busy || sending} onClick={props.onNext}>
              {props.index + 1 === props.total ? '完成关卡 →' : '继续航程 →'}
            </button>
          ) : (
            <div className="scene-help">
              <button
                className="quiet"
                disabled={busy || sending || world.hit !== null}
                onClick={props.onHint}
              >
                听提示
              </button>
              <button className="quiet" disabled={busy || sending} onClick={props.onSkip}>
                先跳过这题
              </button>
            </div>
          )}
          <Notice
            error={props.error}
            onReconnect={() => {
              if (hitOption) void props.onAnswer(hitOption.id);
            }}
          />
          <div className="scene-route" aria-label="本关探索进度">
            {Array.from({ length: props.total }, (_, i) => (
              <span
                key={i}
                className={i < props.index ? 'reached' : i === props.index ? 'current' : ''}
              >
                {i < props.index ? '✓' : i + 1}
              </span>
            ))}
          </div>
        </aside>
      </div>
    </main>
  );
}
