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
} from '../domain/scene-game';
import type { Answer, Exercise, Hint } from '../domain/learning-api';
import { GamePercussion } from '../platform/audio/game-percussion';
import { narration } from './labels';
import { VoiceButton, VoiceFailure, type useLearningVoice } from './learning-voice';
import { SceneWorld } from './scene-world';
import { Notice } from './notice';
import './scene-game.css';

type Props = {
  gameId: string;
  settings?: GameSettings;
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
};
export function SceneGame(props: Props) {
  const { gameId, question, voice, busy, locked, answer, hint, corrected } = props;
  const game = gameCatalog.games.find((g) => g.id === gameId)!;
  const scene = game.scene as Scene;
  const level = props.settings?.level ?? 'gentle',
    speed = props.settings?.speed ?? 'slow';
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
  const [assist, setAssist] = useState(props.reducedMotion);
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
      const next = advanceWorld(
        current.current,
        dt,
        scene,
        question.options.length,
        level,
        speed,
        assist,
      );
      current.current = next;
      setWorld(next);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [stopped, scene, question.options.length, level, speed, assist]);
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
    const next = advanceWorld(
      current.current,
      0,
      scene,
      question.options.length,
      level,
      speed,
      assist,
      action,
    );
    current.current = next;
    setWorld(next);
  }
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
    <main className={`scene-page scene-${scene}`} onClickCapture={props.onInteract}>
      <nav className="scene-nav">
        <button className="quiet" disabled={busy || sending} onClick={props.onExit}>
          ← 保存并退出游戏
        </button>
        <strong>
          {game.icon} {game.title}
        </strong>
        <span>
          第 {props.index + 1} / {props.total} 关
        </span>
      </nav>
      <div className="scene-layout">
        <section className="scene-playfield" aria-label={game.title}>
          <div className="scene-topline">
            <span>
              {gameCatalog.levels[level].label} · {gameCatalog.speeds[speed].label}
            </span>
            <span>{props.total - props.index} 个目的地</span>
          </div>
          <div
            className="scene-stage"
            tabIndex={0}
            role="group"
            aria-label="游戏操作区：方向键控制，空格行动"
            data-scene={scene}
            data-world-x={world.x}
            data-world-distance={world.distance}
            data-world-hit={world.hit ?? ''}
            onKeyDown={(event) => {
              if (event.target !== event.currentTarget) return;
              const action =
                event.key === 'ArrowLeft'
                  ? 'left'
                  : event.key === 'ArrowRight'
                    ? 'right'
                    : event.key === ' ' || event.key === 'ArrowUp'
                      ? 'act'
                      : null;
              if (action) {
                event.preventDefault();
                fire(scene === 'drum' && action !== 'act' ? 'pass' : action);
              }
            }}
          >
            <SceneWorld
              scene={scene}
              world={world}
              options={question.options}
              level={level}
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
                onClick={() =>
                  fire(
                    scene === 'drum' && i !== 1
                      ? 'pass'
                      : i === 0
                        ? 'left'
                        : i === 1
                          ? 'act'
                          : 'right',
                  )
                }
              >
                {label}
              </button>
            ))}
          </div>
          <div className="scene-tools">
            <button
              className="quiet"
              onClick={() => {
                voice.stop();
                setPaused(!paused);
              }}
            >
              {paused ? '▶ 继续' : 'Ⅱ 暂停'}
            </button>
            <button className="quiet" aria-pressed={assist} onClick={() => setAssist(!assist)}>
              🐢 辅助慢动作{assist ? '：开' : '：关'}
            </button>
            {scene === 'drum' && (
              <button className="quiet" aria-pressed={sfx} onClick={() => setSfx(!sfx)}>
                鼓声{sfx ? '：开' : '：关'}
              </button>
            )}
          </div>
          <p className="scene-instruction">{game.controls}</p>
          <p className="scene-motor-note" role="status">
            {world.misses > 0
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
            <VoiceButton
              id={question.audioRef ?? `prompt-${question.id}`}
              kind={question.audioRef ? 'standard' : 'private'}
              voice={voice}
              label={question.audioRef ? '听拼音' : '听题目'}
            />
            <VoiceButton id={game.voiceId} voice={voice} label="听玩法" />
            <VoiceButton id={`prompt-${question.id}`} voice={voice} label="听题目说明" />
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
          {done ? (
            <button className="scene-next" disabled={busy || sending} onClick={props.onNext}>
              继续航程 →
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
