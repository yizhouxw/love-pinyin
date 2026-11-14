import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import {
  clamp,
  fireBeam,
  rhythmNote,
  dock,
  jump,
  planet,
  playgrounds,
  sail,
  sailToDock,
  startPlayground,
  stepPlayground,
  tree,
  type Playground,
  type PlaygroundState,
  type Point,
} from '../domain/playgrounds';
import type { Option } from '../domain/learning-api';
import { GamePercussion } from '../platform/audio/game-percussion';
import './adventure-stage.css';

type Props = {
  taskKey: string;
  running: boolean;
  scene: Playground;
  options: Option[];
  disabled: boolean;
  paused: boolean;
  started: boolean;
  onStart: () => void;
  assist: boolean;
  speed: number;
  difficulty: 'gentle' | 'steady' | 'challenge';
  index: number;
  highlight?: string;
  done: boolean;
  onChoose: (i: number) => void;
  onResume: () => void;
  onPause: () => void;
};
function Fox({ x, y }: { x: number; y: number }) {
  return (
    <g transform={`translate(${x} ${y})`}>
      <path d="M-12 0Q-55 8-32-34L-18-22" fill="#e17636" />
      <path d="M-36-28l4-6 14 12-6 5" fill="#fff0ce" />
      <ellipse cy="-18" rx="19" ry="25" fill="#e8863b" />
      <path d="M-19-40l-3-29 20 13L20-69 19-40" fill="#d96b30" />
      <path d="M-22-46Q0-66 22-46L15-27Q0-19-15-27Z" fill="#f39746" />
      <path d="M-18-37L0-30 18-37Q14-22 0-23-14-22-18-37" fill="#fff0d5" />
      <circle cx="-8" cy="-43" r="2.4" fill="#332b39" />
      <circle cx="8" cy="-43" r="2.4" fill="#332b39" />
      <circle cy="-31" r="3" fill="#332b39" />
      <path d="M-10-2v8m20-8v8" stroke="#663d32" strokeWidth="8" strokeLinecap="round" />
      <path d="M-16-21h32" stroke="#68adb1" strokeWidth="7" />
    </g>
  );
}
export function AdventureStage(p: Props) {
  const [store] = useState(() => {
    let state = { ...startPlayground(), y: p.scene === 'runner' ? 330 : 350 };
    const listeners = new Set<() => void>();
    return {
      read: () => state,
      write: (next: PlaygroundState) => {
        state = next;
        listeners.forEach((fn) => fn());
      },
      subscribe: (fn: () => void) => {
        listeners.add(fn);
        return () => {
          listeners.delete(fn);
        };
      },
    };
  });
  const world = useSyncExternalStore(store.subscribe, store.read);
  const config = useRef(p);
  useEffect(() => {
    config.current = p;
  });
  const sent = useRef(false);
  const stage = useRef<HTMLDivElement>(null);
  const pointer = useRef<{ id: number; start: Point; last: Point; moved: boolean } | null>(null);
  const drums = useRef<GamePercussion | null>(null);
  const held = useRef(new Set<string>());
  useEffect(() => {
    sent.current = false;
    const old = store.read();
    store.write({ ...old, hit: null, shot: null, chosen: null });
  }, [p.taskKey, store]);
  useEffect(() => {
    const clear = () => held.current.clear();
    const down = (e: KeyboardEvent) => {
      if (
        document.querySelector('dialog[open]') ||
        (e.target instanceof Element &&
          e.target.closest('input,select,textarea,[contenteditable=true]'))
      )
        return;
      if (!['ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight', 'Space', 'KeyP'].includes(e.code))
        return;
      if (
        e.code === 'Space' &&
        e.target instanceof Element &&
        e.target.closest('button') &&
        !e.target.closest('.adventure-run-controls,.flight-controls')
      )
        return;
      e.preventDefault();
      const c = config.current;
      if (e.code === 'KeyP') {
        if (!e.repeat) c.onPause();
        return;
      }
      if (!c.running) return;
      held.current.add(e.code);
      if (c.scene === 'space' && e.code === 'Space' && !c.disabled && !e.repeat)
        store.write(fireBeam(store.read()));
      if (c.scene === 'runner' && ['ArrowUp', 'Space'].includes(e.code) && !e.repeat)
        store.write(jump(store.read()));
    };
    const up = (e: KeyboardEvent) => held.current.delete(e.code);
    window.addEventListener('keydown', down);
    window.addEventListener('keyup', up);
    window.addEventListener('blur', clear);
    document.addEventListener('visibilitychange', clear);
    return () => {
      window.removeEventListener('keydown', down);
      window.removeEventListener('keyup', up);
      window.removeEventListener('blur', clear);
      document.removeEventListener('visibilitychange', clear);
    };
  }, [store]);
  useEffect(() => {
    const cancel = () => {
      pointer.current = null;

      store.write({ ...store.read(), destination: null, route: [] });
    };
    window.addEventListener('resize', cancel);
    return () => window.removeEventListener('resize', cancel);
  }, [store]);

  useEffect(() => {
    drums.current = new GamePercussion();
    return () => drums.current?.close();
  }, []);
  useEffect(() => {
    if (p.disabled || p.paused) {
      held.current.clear();
      pointer.current = null;
      store.write({ ...store.read(), destination: null, route: [] });
    }
  }, [p.disabled, p.paused, store]);
  useEffect(() => {
    if (!p.running || p.paused) return;
    let raf = 0,
      last = 0;
    const tick = (time: number) => {
      const dt = last ? (time - last) / 1000 : 0;
      last = time;
      if (!document.hidden) {
        let current = store.read();
        if (p.scene === 'space') {
          const dx = Number(held.current.has('ArrowRight')) - Number(held.current.has('ArrowLeft'));
          const dy = Number(held.current.has('ArrowDown')) - Number(held.current.has('ArrowUp'));
          current = {
            ...current,
            x: clamp(current.x + dx * dt * 280, 25, 455),
            y: clamp(current.y + dy * dt * 280, 180, 370),
          };
          if (held.current.has('Space') && !p.disabled) current = fireBeam(current);
        }
        const next = stepPlayground(current, dt, {
          interactive: !p.disabled,
          scene: p.scene,
          difficulty: p.difficulty,
          count: p.options.length,
          speed: p.speed * (p.scene === 'boat' && pointer.current?.moved ? 2.5 : 1),
          assist: p.assist,
        });
        store.write(next);
        if (!p.disabled && next.hit !== null && !sent.current) {
          sent.current = true;
          config.current.onChoose(next.hit);
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [
    p.running,
    p.disabled,
    p.paused,
    p.scene,
    p.options.length,
    p.speed,
    p.assist,
    p.difficulty,
    store,
  ]);
  function choose(i: number) {
    if (p.disabled || p.paused || sent.current) return;
    stage.current?.focus({ preventScroll: true });
    if (p.scene === 'drum') {
      drums.current?.hit(i % 2 === 1);
      if (
        Math.abs(rhythmNote(store.read().time, i) - playgrounds.drum.strikeY) >
        playgrounds.drum.window
      )
        return;
      sent.current = true;
      store.write({ ...store.read(), hit: i });
      p.onChoose(i);
    } else if (p.scene === 'boat') store.write(sailToDock(store.read(), i, p.options.length));
    else if (p.scene === 'space')
      store.write({ ...store.read(), x: planet(i, p.options.length).x });
    else {
      const s = store.read();
      const current = tree(s, p.options.length);
      const ordinal = current.ordinal + ((i - current.index + p.options.length) % p.options.length);
      store.write(
        jump({
          ...s,
          distance: playgrounds.runner.firstTree + ordinal * playgrounds.runner.treeSpacing - 170,
          y: 330,
        }),
      );
    }
  }
  function point(e: React.PointerEvent<HTMLDivElement>): Point {
    const rect = e.currentTarget.getBoundingClientRect();
    return {
      x: ((e.clientX - rect.left) / rect.width) * 480,
      y: ((e.clientY - rect.top) / rect.height) * 400,
    };
  }
  const fruit = tree(world, p.options.length);
  const firing = world.shot !== null;
  useEffect(() => {
    if (firing || world.hit !== null) drums.current?.hit(world.hit === null);
  }, [firing, world.hit]);
  const canPlay = !p.disabled && !p.paused;
  const names = {
    runner: '森林跳跃冒险',
    boat: '河湾救援航行',
    drum: '拼音节奏轨道',
    space: '星际飞行射击',
  };
  return (
    <div className={`adventure adventure-${p.scene}`}>
      <div
        className="adventure-canvas"
        ref={stage}
        role="group"
        tabIndex={0}
        aria-label={names[p.scene]}
        data-scene={p.scene}
        data-started={p.started}
        data-speed-factor={p.speed}
        data-world-distance={world.distance}
        data-world-x={world.x}
        data-world-y={world.y}
        data-world-hit={world.hit ?? ''}
        data-motor-misses={world.misses}
        data-rhythm-index={0}
        onPointerDown={(e) => {
          if (
            pointer.current ||
            !e.isPrimary ||
            !canPlay ||
            (e.target instanceof Element && e.target.closest('button'))
          )
            return;
          e.preventDefault();
          const at = point(e);
          pointer.current = { id: e.pointerId, start: at, last: at, moved: false };
          e.currentTarget.setPointerCapture(e.pointerId);
          stage.current?.focus({ preventScroll: true });
          if (p.scene === 'runner') {
            drums.current?.hit();
            store.write(jump(store.read()));
          }
          if (p.scene === 'boat') store.write(sail(store.read(), at));
          if (p.scene === 'space')
            store.write({ ...store.read(), x: clamp(at.x, 25, 455), y: clamp(at.y, 180, 370) });
        }}
        onPointerMove={(e) => {
          const active = pointer.current;
          if (!active || active.id !== e.pointerId || !canPlay) return;
          const at = point(e);
          active.last = at;
          if (Math.hypot(at.x - active.start.x, at.y - active.start.y) > 5) active.moved = true;
          if (p.scene === 'boat') store.write(sail(store.read(), at));
          if (p.scene === 'space')
            store.write({ ...store.read(), x: clamp(at.x, 25, 455), y: clamp(at.y, 180, 370) });
        }}
        onPointerUp={(e) => {
          const active = pointer.current;
          if (!active || active.id !== e.pointerId) return;

          pointer.current = null;

          if (p.scene === 'boat' && active.moved)
            store.write({ ...store.read(), destination: null, route: [] });
        }}
        onPointerCancel={() => {
          pointer.current = null;

          store.write({ ...store.read(), destination: null, route: [] });
        }}
        onLostPointerCapture={() => {
          if (pointer.current) {
            pointer.current = null;

            store.write({ ...store.read(), destination: null, route: [] });
          }
        }}
      >
        <svg viewBox="0 0 480 400" aria-label={names[p.scene]} role="img">
          <defs>
            <linearGradient id={`sky-${p.scene}`} x2="0" y2="1">
              <stop
                stopColor={
                  p.scene === 'space' ? '#171e50' : p.scene === 'boat' ? '#78d6d4' : '#bde5d9'
                }
              />
              <stop
                offset="1"
                stopColor={
                  p.scene === 'space' ? '#59608d' : p.scene === 'boat' ? '#319fad' : '#f9edc6'
                }
              />
            </linearGradient>
            <pattern id="river-ripples" width="85" height="55" patternUnits="userSpaceOnUse">
              <path
                d="M10 25q15 6 30 0m12 20h14"
                stroke="#d1ffff"
                strokeOpacity=".35"
                strokeWidth="2"
                fill="none"
              />
            </pattern>
            <linearGradient id="forest-depth" x2="0" y2="1">
              <stop stopColor="#102e38" />
              <stop offset=".65" stopColor="#357966" />
              <stop offset="1" stopColor="#aec480" />
            </linearGradient>
            <radialGradient id="nebula">
              <stop stopColor="#366194" stopOpacity=".6" />
              <stop offset="1" stopColor="#101a37" stopOpacity="0" />
            </radialGradient>
          </defs>
          <rect width="480" height="400" fill={`url(#sky-${p.scene})`} />
          {p.scene === 'runner' && (
            <>
              <rect width="480" height="400" fill="url(#forest-depth)" />
              <path d="M320 0L110 330H175L400 0Z" fill="#e8f8b4" opacity=".09" />
              {Array.from({ length: 24 }, (_, i) => (
                <path
                  key={i}
                  d={`M${i * 27 - ((world.distance * 0.12) % 27)} 0v${100 + (i % 5) * 28}`}
                  stroke="#102f38"
                  strokeWidth={5 + (i % 3) * 4}
                  opacity=".45"
                />
              ))}
              <circle cx="385" cy="60" r="30" fill="#fff5be" opacity=".8" />
              <path d="M0 205Q90 75 180 170T480 130V400H0" fill="#7fbea6" />
              <path d="M0 260Q100 150 210 240T480 210V400H0" fill="#47977d" />
              {[0, 1, 2, 3, 4].map((i) => {
                const x = i * 150 - ((world.distance * 0.25) % 150);
                return (
                  <g key={i} transform={`translate(${x} 0)`}>
                    <path d="M18 110v220" stroke="#668064" strokeWidth="12" />
                    <ellipse cx="18" cy="105" rx="49" ry="72" fill="#37846e" />
                    <ellipse cx="30" cy="85" rx="28" ry="44" fill="#4f9c78" />
                  </g>
                );
              })}
              <path d="M0 330Q100 320 200 332T480 330V400H0" fill="#b6cc70" />
              <path d="M0 352h480" stroke="#e4d298" strokeWidth="34" />
              {Array.from({ length: 4 }, (_, offset) => {
                const ordinal = Math.max(0, fruit.ordinal - 1) + offset;
                const x =
                  playgrounds.runner.firstTree +
                  ordinal * playgrounds.runner.treeSpacing -
                  world.distance;
                return (
                  <g key={ordinal} transform={`translate(${x} 0)`}>
                    <path d="M0 330V210" stroke="#9a7951" strokeWidth="10" />
                    <ellipse cy="205" rx="55" ry="38" fill="#5c9d6b" />
                    <circle cy="251" r="30" fill="#f6c951" />
                    <path d="M0 223q-5-12 8-15" fill="none" stroke="#4d794a" strokeWidth="4" />
                    <text y="258" textAnchor="middle" fontSize="24" fill="#463b30">
                      {p.options[ordinal % p.options.length]?.label}
                    </text>
                    <g transform="translate(-120 318)">
                      <rect x="-18" y="-8" width="36" height="20" rx="7" fill="#ae7752" />
                      <circle cx="15" cy="2" r="9" fill="#d6aa76" />
                    </g>
                  </g>
                );
              })}
              {Array.from({ length: 12 }, (_, i) => {
                const x = i * 48 - ((world.distance * 1.15) % 48);
                return (
                  <g key={i} transform={`translate(${x} 380)`}>
                    <path d="M0 20V-12M0 2L-12-8M0 8L15-6" stroke="#1e574c" strokeWidth="4" />
                    <path d="M0 0L-16-18 0-10 15-22Z" fill="#337764" />
                  </g>
                );
              })}
              <path d="M0 367H480M0 347H480" stroke="#806b49" strokeWidth="1" opacity=".4" />
              <Fox x={110} y={world.y} />
              <text x="24" y="30" fontSize="15" fill="#244e42">
                ✦ 跳起来，摘拼音果
              </text>
            </>
          )}
          {p.scene === 'boat' && (
            <>
              <rect width="480" height="400" fill="url(#river-ripples)" />
              <path d="M0 0H480V31Q370 55 240 33T0 42Z" fill="#9fc987" />
              <path d="M0 0Q35 200 12 400H0M480 0Q448 260 475 400H480" fill="#83b984" />
              {p.options.map((o, i) => {
                const at = dock(i, p.options.length);
                return (
                  <g key={o.id} transform={`translate(${at.x} ${at.y})`}>
                    <rect x="-30" y="-8" width="60" height="50" rx="8" fill="#bb8e61" />
                    <path d="M-24 8h48m-48 14h48" stroke="#e5bf82" strokeWidth="3" />
                    <path d="M-28-15v-35h56v35Z" fill="#fff5d4" stroke="#58866f" strokeWidth="3" />
                    <text y="-26" textAnchor="middle" fontSize="24" fill="#254b47">
                      {o.label}
                    </text>
                  </g>
                );
              })}
              {playgrounds.boat.rocks.map((r, i) => (
                <g key={i}>
                  <ellipse
                    cx={r.x}
                    cy={r.y + 10}
                    rx={r.radius + 10}
                    ry={r.radius * 0.6}
                    fill="#dcffff"
                    opacity=".4"
                  />
                  <path
                    d={`M${r.x - r.radius} ${r.y + 10}l12 -32 27 -6 22 27-12 20Z`}
                    fill="#738b8f"
                  />
                  <path d={`M${r.x - 15} ${r.y - 22}l15 -5 18 20-30 -3Z`} fill="#a8bbb6" />
                </g>
              ))}
              {playgrounds.boat.ducklings.map((d, i) =>
                world.collected.includes(i) ? null : (
                  <g key={i} transform={`translate(${d.x} ${d.y})`}>
                    <ellipse rx="12" ry="8" fill="#ffdf71" />
                    <circle cx="8" cy="-8" r="8" fill="#ffe592" />
                    <path d="M14-10l9 4-9 2" fill="#db8844" />
                    <circle cx="10" cy="-10" r="1.5" fill="#394553" />
                  </g>
                ),
              )}
              {world.destination && (
                <circle
                  cx={world.destination.x}
                  cy={world.destination.y}
                  r="12"
                  fill="none"
                  stroke="#fff"
                  strokeWidth="2"
                  strokeDasharray="4 4"
                />
              )}
              <g transform={`translate(${world.x} ${world.y})`}>
                <ellipse cy="7" rx="25" ry="33" fill="#176c88" opacity=".35" />
                <path
                  d="M0-32Q35-8 18 29Q0 40-18 29-35-8 0-32"
                  fill="#e8aa61"
                  stroke="#825d48"
                  strokeWidth="3"
                />
                <path d="M-15 8h30" stroke="#f6d393" strokeWidth="8" />
                <circle cy="-7" r="11" fill="#e9793c" />
                <path d="M-9-13l-4-12 12 7 11-7-2 13" fill="#e9793c" />
                <path d="M-9-6L0-1 9-6" fill="#fff2d2" />
              </g>
            </>
          )}
          {p.scene === 'space' && (
            <>
              <ellipse cx="380" cy="180" rx="280" ry="210" fill="url(#nebula)" />
              <path d="M120 400L220 0M360 400L260 0" stroke="#83bde6" opacity=".13" />
              {Array.from({ length: 32 }, (_, i) => (
                <circle
                  key={i}
                  cx={(i * 137 + 31) % 480}
                  cy={(i * 67 + 12 + world.time * (12 + (i % 4) * 8)) % 400}
                  r={i % 3 === 0 ? 2 : 1}
                  fill="#fff4c7"
                  opacity=".7"
                />
              ))}
              {p.options.map((o, i) => {
                const at = planet(i, p.options.length);
                return (
                  <g key={o.id} transform={`translate(${at.x} ${at.y})`}>
                    <path
                      d="M-42 12L-31-15-15-24H15L31-15 42 12 24 21H-24Z"
                      fill="#193651"
                      stroke="#6ebeda"
                      strokeWidth="2"
                    />
                    <path
                      d="M-38 10H-24M24 10H38M-12-24L-7-32H7L12-24"
                      stroke="#f4ce79"
                      strokeWidth="4"
                    />
                    <rect x="-22" y="-17" width="44" height="34" rx="5" fill="#cef2ef" />
                    <text textAnchor="middle" y="8" fill="#293255" fontSize="24">
                      {o.label}
                    </text>
                  </g>
                );
              })}
              <g transform={`translate(${world.x} ${world.y})`}>
                <path d="M0-30L22 22 0 10-22 22Z" fill="#bdefff" stroke="#63d9ff" strokeWidth="2" />
                <path d="M-7 18L0 40 7 18" fill="#ffb754" />
                <path d="M0-10v16" stroke="#1a3964" strokeWidth="5" />
              </g>
              {world.shot && (
                <path d={`M${world.shot.x} ${world.shot.y}v20`} stroke="#7bffff" strokeWidth="5" />
              )}
            </>
          )}
          {p.scene === 'drum' && (
            <>
              <rect width="480" height="400" fill="#101d38" />
              {Array.from({ length: 12 }, (_, i) => (
                <path
                  key={i}
                  d={`M0 ${(i * 40 + world.time * 25) % 400}H480`}
                  stroke="#32496c"
                  opacity=".3"
                />
              ))}
              {p.options.map((o, i) => {
                const x = 60 + (i * 360) / Math.max(1, p.options.length - 1);
                const y = rhythmNote(world.time, i);
                return (
                  <g key={o.id}>
                    <path d={`M${x} 0V400`} stroke="#3a537a" strokeWidth="2" />
                    <rect
                      x={x - 38}
                      y="275"
                      width="76"
                      height="70"
                      rx="8"
                      fill="#233959"
                      stroke="#6ee7ec"
                      strokeWidth="2"
                    />
                    <rect x={x - 32} y={y - 23} width="64" height="46" rx="7" fill="#78e0e1" />
                    <text x={x} y={y + 8} textAnchor="middle" fontSize="25" fill="#10263d">
                      {o.label}
                    </text>
                  </g>
                );
              })}
              <path d="M15 310H465" stroke="#ffe18b" strokeWidth="3" />
            </>
          )}
        </svg>
        {(p.scene === 'boat' || p.scene === 'space') && (
          <div className="adventure-targets">
            {p.options.map((o, i) => {
              const at =
                p.scene === 'boat' ? dock(i, p.options.length) : planet(i, p.options.length);
              return (
                <button
                  key={o.id}
                  data-option-id={o.id}
                  disabled={!canPlay}
                  className={o.id === p.highlight ? 'highlight' : ''}
                  style={{ left: `${at.x / 4.8}%`, top: `${at.y / 4}%` }}
                  aria-label={`${p.scene === 'boat' ? '驶向' : '投递到'} ${o.label}`}
                  onClick={() => choose(i)}
                >
                  <span className="screen-reader-only">{o.label}</span>
                </button>
              );
            })}
          </div>
        )}
        {p.scene === 'drum' && (
          <div className="adventure-drum-picks">
            {p.options.map((o, i) => (
              <button
                disabled={!canPlay}
                key={o.id}
                data-option-id={o.id}
                className={o.id === p.highlight ? 'highlight' : ''}
                style={{
                  left: `${(60 + (i * 360) / Math.max(1, p.options.length - 1)) / 4.8}%`,
                  top: '88%',
                }}
                onClick={() => choose(i)}
                aria-label={`敲响 ${o.label}`}
              >
                {o.label}
              </button>
            ))}
          </div>
        )}
        {!p.started && (
          <div className="adventure-overlay">
            <strong>准备好了吗？</strong>
            <button onClick={p.onStart}>▶ 开始游戏</button>
          </div>
        )}
        {p.started && p.paused && (
          <div className="adventure-overlay">
            <strong>先停一停</strong>
            <button onClick={p.onResume}>▶ 继续游戏</button>
          </div>
        )}
        {world.hit !== null && (!p.done || p.scene !== 'drum') && (
          <div className="adventure-arrival" role="status">
            {p.done
              ? {
                  runner: '✦ 摘到啦！',
                  boat: '✦ 靠岸啦！',
                  drum: '✦ 一起合奏！',
                  space: '✦ 送到啦！',
                }[p.scene]
              : '已选择'}{' '}
            {p.options[world.hit]?.label}
          </div>
        )}
      </div>
      {p.scene === 'runner' && (
        <div className="adventure-run-controls">
          <button
            disabled={!canPlay}
            onClick={() => {
              stage.current?.focus({ preventScroll: true });
              store.write(jump(store.read()));
            }}
            onKeyDown={(e) => {
              if (e.code === 'ArrowUp' || e.code === 'Space') {
                e.preventDefault();
                if (canPlay && !e.repeat) store.write(jump(store.read()));
              }
            }}
          >
            跳起来 ↑
          </button>
          <div aria-label="选择果树">
            {p.options.map((o, i) => (
              <button
                className={o.id === p.highlight ? 'highlight' : 'quiet'}
                disabled={!canPlay}
                key={o.id}
                data-option-id={o.id}
                onClick={() => choose(i)}
              >
                摘 {o.label}
              </button>
            ))}
          </div>
        </div>
      )}
      {p.scene === 'boat' && (
        <div className="adventure-caption">
          <span>🦆 {world.collected.length} / 3</span>
          <span>手指带着小船走 · 松手停船</span>
          <button
            className="quiet"
            disabled={!canPlay}
            onClick={() => store.write({ ...world, destination: null, route: [] })}
          >
            停船
          </button>
        </div>
      )}
      {p.scene === 'space' && (
        <div className="flight-controls">
          <button
            disabled={!canPlay}
            onClick={() => store.write({ ...store.read(), x: clamp(world.x - 45, 25, 455) })}
          >
            ←
          </button>
          <button
            disabled={!canPlay}
            onPointerDown={(e) => {
              e.currentTarget.setPointerCapture(e.pointerId);
              held.current.add('Space');
            }}
            onPointerUp={() => held.current.delete('Space')}
            onPointerCancel={() => held.current.delete('Space')}
            onLostPointerCapture={() => held.current.delete('Space')}
            onClick={() => store.write(fireBeam(store.read()))}
          >
            发射 · 空格
          </button>
          <button
            disabled={!canPlay}
            onClick={() => store.write({ ...store.read(), x: clamp(world.x + 45, 25, 455) })}
          >
            →
          </button>
        </div>
      )}
      {p.scene === 'drum' && (
        <p className="adventure-caption">听拼音，在音符经过金线时敲对应轨道；可等待下一轮。</p>
      )}
      {world.misses > 0 && world.hit === null && (
        <p className="adventure-motor-note" role="status">
          {p.scene === 'boat'
            ? '碰到礁石啦，绕个弯继续。'
            : p.scene === 'space'
              ? '包裹回来啦，换个方向再试。'
              : '绊了一下，继续跳起来！'}
        </p>
      )}
    </div>
  );
}
