import { useEffect, useRef, useState, useSyncExternalStore } from 'react';
import {
  clamp,
  deliveryVelocity,
  dock,
  jump,
  planet,
  playgrounds,
  sail,
  sailToDock,
  startPlayground,
  stepPlayground,
  throwParcel,
  trajectory,
  tree,
  type Playground,
  type PlaygroundState,
  type Point,
} from '../domain/playgrounds';
import type { Option } from '../domain/learning-api';
import { GamePercussion } from '../platform/audio/game-percussion';
import './adventure-stage.css';

type Props = {
  scene: Playground;
  options: Option[];
  disabled: boolean;
  paused: boolean;
  still: boolean;
  assist: boolean;
  speed: number;
  difficulty: 'gentle' | 'steady' | 'challenge';
  index: number;
  highlight?: string;
  done: boolean;
  rhythmEnabled: boolean;
  onChoose: (i: number) => void;
  onFinished: () => void;
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
  const [aim, setAim] = useState<Point | null>(null);
  const [rhythmIndex, setRhythmIndex] = useState(0);
  const [demo, setDemo] = useState<number | null>(null);
  const [rhythmMessage, setRhythmMessage] = useState('');
  const [showDemo, setShowDemo] = useState(false);
  const drums = useRef<GamePercussion | null>(null);
  const rhythm = playgrounds.rhythms[p.difficulty][p.index % 2]!;
  useEffect(() => {
    const cancel = () => {
      pointer.current = null;
      setAim(null);
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
      pointer.current = null;
      store.write({ ...store.read(), destination: null, route: [] });
    }
  }, [p.disabled, p.paused, store]);
  useEffect(() => {
    if (p.disabled || p.paused || p.still) return;
    let raf = 0,
      last = 0;
    const tick = (time: number) => {
      const dt = last ? (time - last) / 1000 : 0;
      last = time;
      if (!document.hidden) {
        const next = stepPlayground(store.read(), dt, {
          scene: p.scene,
          difficulty: p.difficulty,
          count: p.options.length,
          speed: p.speed * (p.scene === 'boat' && pointer.current?.moved ? 2.5 : 1),
          assist: p.assist,
          still: p.still,
        });
        store.write(next);
        if (next.hit !== null && !sent.current) {
          sent.current = true;
          config.current.onChoose(next.hit);
        }
      }
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [
    p.disabled,
    p.paused,
    p.still,
    p.scene,
    p.options.length,
    p.speed,
    p.assist,
    p.difficulty,
    store,
  ]);
  useEffect(() => {
    if (!showDemo || p.paused || !p.rhythmEnabled) return;
    const beatMilliseconds = Math.max(360, 650 / p.speed);
    const timers = rhythm.map((beat, i) =>
      window.setTimeout(
        () => {
          setDemo(beat);
          drums.current?.hit(beat === 1);
        },
        400 + i * beatMilliseconds,
      ),
    );
    timers.push(
      window.setTimeout(
        () => {
          setDemo(null);
          setShowDemo(false);
          setRhythmMessage('轮到你啦！');
        },
        500 + rhythm.length * beatMilliseconds,
      ),
    );
    return () => timers.forEach(window.clearTimeout);
  }, [showDemo, p.paused, p.rhythmEnabled, p.speed, rhythm]);
  function choose(i: number) {
    if (p.disabled || p.paused) return;
    stage.current?.focus({ preventScroll: true });
    if (p.still || p.scene === 'drum') {
      sent.current = true;
      store.write({ ...store.read(), hit: i });
      p.onChoose(i);
    } else if (p.scene === 'boat') store.write(sailToDock(store.read(), i, p.options.length));
    else if (p.scene === 'space')
      store.write(throwParcel(store.read(), deliveryVelocity(i, p.options.length), i));
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
  function beat(value: number) {
    if (!p.done || !p.rhythmEnabled || p.paused || showDemo || rhythmIndex >= rhythm.length) return;
    drums.current?.hit(value === 1);
    if (rhythm[rhythmIndex] === value) {
      const next = rhythmIndex + 1;
      setRhythmIndex(next);
      setRhythmMessage(next === rhythm.length ? '合奏完成！' : '继续，慢慢来。');
      if (next === rhythm.length) p.onFinished();
    } else {
      setRhythmIndex(0);
      setRhythmMessage('再听一遍，从第一下开始。');
    }
  }
  function point(e: React.PointerEvent<HTMLDivElement>): Point {
    const rect = e.currentTarget.getBoundingClientRect();
    return {
      x: ((e.clientX - rect.left) / rect.width) * 480,
      y: ((e.clientY - rect.top) / rect.height) * 400,
    };
  }
  function velocity(at: Point): Point {
    return {
      x: clamp(((pointer.current?.start.x ?? 240) - at.x) * 3, -400, 400),
      y: clamp(-250 - (at.y - (pointer.current?.start.y ?? 350)) * 5, -510, -80),
    };
  }
  const fruit = tree(world, p.options.length);
  const canPlay = !p.disabled && !p.paused && !(p.scene === 'space' && world.shot);
  const names = {
    runner: '森林跳跃冒险',
    boat: '河湾救援航行',
    drum: '鼓岛动物乐队',
    space: '星际包裹弹射',
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
        data-still={p.still}
        data-speed-factor={p.speed}
        data-world-distance={world.distance}
        data-world-x={world.x}
        data-world-y={world.y}
        data-world-hit={world.hit ?? ''}
        data-motor-misses={world.misses}
        data-rhythm-index={rhythmIndex}
        onKeyDown={(e) => {
          if (e.code === 'Escape' || e.code === 'KeyP') {
            e.preventDefault();
            p.onPause();
            return;
          }
          if (e.target instanceof Element && e.target.closest('button')) return;
          if (!canPlay) return;
          if (['Space', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.code))
            e.preventDefault();
          if (p.scene === 'runner' && (e.code === 'Space' || e.code === 'ArrowUp'))
            store.write(jump(store.read()));
          if (p.scene === 'boat') {
            const delta = {
              ArrowLeft: [-65, 0],
              ArrowRight: [65, 0],
              ArrowUp: [0, -65],
              ArrowDown: [0, 65],
            }[e.code];
            if (delta)
              store.write(sail(store.read(), { x: world.x + delta[0]!, y: world.y + delta[1]! }));
          }
        }}
        onPointerDown={(e) => {
          if (
            pointer.current ||
            !e.isPrimary ||
            !canPlay ||
            p.still ||
            (e.target instanceof Element && e.target.closest('button'))
          )
            return;
          const at = point(e);
          pointer.current = { id: e.pointerId, start: at, last: at, moved: false };
          e.currentTarget.setPointerCapture(e.pointerId);
          stage.current?.focus({ preventScroll: true });
          if (p.scene === 'runner') store.write(jump(store.read()));
          if (p.scene === 'boat') store.write(sail(store.read(), at));
          if (p.scene === 'space') setAim(velocity(at));
        }}
        onPointerMove={(e) => {
          const active = pointer.current;
          if (!active || active.id !== e.pointerId || !canPlay) return;
          const at = point(e);
          active.last = at;
          if (Math.hypot(at.x - active.start.x, at.y - active.start.y) > 5) active.moved = true;
          if (p.scene === 'boat') store.write(sail(store.read(), at));
          if (p.scene === 'space') setAim(velocity(at));
        }}
        onPointerUp={(e) => {
          const active = pointer.current;
          if (!active || active.id !== e.pointerId) return;
          const releaseVelocity = velocity(active.last);
          pointer.current = null;
          setAim(null);
          if (canPlay && p.scene === 'space')
            store.write(throwParcel(store.read(), releaseVelocity));
          if (p.scene === 'boat' && active.moved)
            store.write({ ...store.read(), destination: null, route: [] });
        }}
        onPointerCancel={() => {
          pointer.current = null;
          setAim(null);
          store.write({ ...store.read(), destination: null, route: [] });
        }}
        onLostPointerCapture={() => {
          if (pointer.current) {
            pointer.current = null;
            setAim(null);
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
          </defs>
          <rect width="480" height="400" fill={`url(#sky-${p.scene})`} />
          {p.scene === 'runner' && (
            <>
              <circle cx="385" cy="60" r="30" fill="#fff5be" />
              <path d="M0 205Q90 75 180 170T480 130V400H0" fill="#7fbea6" />
              <path d="M0 260Q100 150 210 240T480 210V400H0" fill="#47977d" />
              {[0, 1, 2, 3, 4].map((i) => {
                const x = i * 150 - ((p.still ? 0 : world.distance * 0.25) % 150);
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
              <g transform={`translate(${fruit.x} 0)`}>
                <path d="M0 330V210" stroke="#9a7951" strokeWidth="10" />
                <ellipse cy="205" rx="55" ry="38" fill="#5c9d6b" />
                <circle cy="251" r="30" fill="#f6c951" />
                <path d="M0 223q-5-12 8-15" fill="none" stroke="#4d794a" strokeWidth="4" />
                <text y="258" textAnchor="middle" fontSize="24" fill="#463b30">
                  {p.options[fruit.index]?.label}
                </text>
              </g>
              <g transform={`translate(${fruit.x - 120} 318)`}>
                <rect x="-18" y="-8" width="36" height="20" rx="7" fill="#ae7752" />
                <circle cx="15" cy="2" r="9" fill="#d6aa76" />
              </g>
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
              {Array.from({ length: 32 }, (_, i) => (
                <circle
                  key={i}
                  cx={(i * 137 + 31) % 480}
                  cy={(i * 67 + 12) % 370}
                  r={i % 3 === 0 ? 2 : 1}
                  fill="#fff4c7"
                  opacity=".7"
                />
              ))}
              <ellipse cx="240" cy="400" rx="200" ry="65" fill="#8d8bb9" />
              <ellipse cx="240" cy="409" rx="155" ry="55" fill="#b3a4c9" />
              {p.options.map((o, i) => {
                const at = planet(i, p.options.length);
                return (
                  <g key={o.id} transform={`translate(${at.x} ${at.y})`}>
                    <ellipse
                      rx="43"
                      ry="14"
                      fill="none"
                      stroke={['#e5b89f', '#afd1b8', '#a0c7e0', '#dfca92'][i % 4]}
                      strokeWidth="7"
                      transform="rotate(-20)"
                    />
                    <circle r="31" fill={['#e9a780', '#9cceaa', '#97bfdd', '#d7b8d6'][i % 4]} />
                    <path d="M-20-18q20-12 33 3" stroke="#ffffff60" strokeWidth="5" fill="none" />
                    <text textAnchor="middle" y="8" fill="#293255" fontSize="24">
                      {o.label}
                    </text>
                  </g>
                );
              })}
              {playgrounds.space.rocks.map((r, i) => (
                <g key={i}>
                  <circle cx={r.x} cy={r.y} r={r.radius} fill="#88849a" />
                  <circle cx={r.x - 6} cy={r.y - 7} r="7" fill="#66677f" />
                  <circle cx={r.x + 8} cy={r.y + 8} r="5" fill="#aaa2b4" />
                </g>
              ))}
              {aim && (
                <polyline
                  points={trajectory(aim)
                    .map((q) => `${q.x},${q.y}`)
                    .join(' ')}
                  stroke="#ffe7a3"
                  strokeWidth="3"
                  strokeDasharray="4 7"
                  fill="none"
                />
              )}
              <path
                d="M225 377v-45m30 45v-45"
                stroke="#d8bd8c"
                strokeWidth="9"
                strokeLinecap="round"
              />
              <path
                d={`M225 335L${aim ? clamp(240 - aim.x / 5, 200, 280) : 240} ${aim ? 370 : 345} 255 335`}
                stroke="#fce0a0"
                strokeWidth="4"
                fill="none"
              />
              <g transform={`translate(${world.shot?.x ?? 240} ${world.shot?.y ?? 350})`}>
                <rect x="-10" y="-10" width="20" height="20" rx="4" fill="#ffd97c" />
                <path d="M0-10v20m-10-10h20" stroke="#db9163" strokeWidth="3" />
              </g>
            </>
          )}
          {p.scene === 'drum' && (
            <>
              <circle cx="380" cy="70" r="33" fill="#fff2b5" />
              <path
                d="M0 230Q50 150 110 225Q170 160 230 230Q340 140 480 220V400H0"
                fill="#70b7a0"
              />
              <ellipse cx="240" cy="340" rx="230" ry="80" fill="#e7cb86" />
              <ellipse cx="240" cy="338" rx="190" ry="43" fill="#cda673" />
              {[90, 240, 390].map((x, i) => (
                <g key={x} transform={`translate(${x} 210)`}>
                  <ellipse cy="3" rx="34" ry="44" fill={['#d4a270', '#8db5ad', '#dc9e77'][i]} />
                  <circle cy="-40" r="31" fill={['#dfb584', '#a0c6b3', '#e6b58b'][i]} />
                  <circle cx="-23" cy="-65" r="12" fill={['#dfb584', '#a0c6b3', '#e6b58b'][i]} />
                  <circle cx="23" cy="-65" r="12" fill={['#dfb584', '#a0c6b3', '#e6b58b'][i]} />
                  <circle cx="-10" cy="-44" r="3" fill="#39484b" />
                  <circle cx="10" cy="-44" r="3" fill="#39484b" />
                  <path d="M-6-32q6 5 12 0" fill="none" stroke="#39484b" strokeWidth="2" />
                  <path d="M-35 20l7 49h56l7-49" fill={['#d67b59', '#679aa7', '#b18db3'][i]} />
                  <ellipse cy="20" rx="35" ry="14" fill="#ffebbe" />
                </g>
              ))}
              <text x="240" y="55" textAnchor="middle" fontSize="24" fill="#37605a">
                小岛合奏时间
              </text>
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
                onClick={() => choose(i)}
                aria-label={`敲响 ${o.label}`}
              >
                {o.label}
              </button>
            ))}
          </div>
        )}
        {p.paused && (
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
          <button disabled={!canPlay} onClick={() => store.write(jump(store.read()))}>
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
        <p className="adventure-caption" aria-live="polite">
          {world.shot ? '包裹飞行中…' : '按住画面向下拉，松手投递 · 也可轻点星球'}
        </p>
      )}
      {p.scene === 'drum' && p.done && (
        <div className="adventure-rhythm">
          <div className="rhythm-score" aria-label="节奏乐谱">
            {rhythm.map((beat, i) => (
              <span
                key={i}
                className={i < rhythmIndex ? 'played' : i === rhythmIndex ? 'current' : ''}
              >
                {beat === 0 ? '●' : '◎'}
              </span>
            ))}
          </div>
          <button
            className="quiet"
            disabled={!p.rhythmEnabled || p.paused || showDemo}
            onClick={() => {
              setRhythmIndex(0);
              setShowDemo(true);
            }}
          >
            ▶ 听小乐队示范
          </button>
          <div className="rhythm-pads">
            <button
              aria-pressed={demo === 0}
              disabled={!p.rhythmEnabled || p.paused || showDemo}
              onClick={() => beat(0)}
            >
              ● 咚 · 鼓心
            </button>
            <button
              aria-pressed={demo === 1}
              disabled={!p.rhythmEnabled || p.paused || showDemo}
              onClick={() => beat(1)}
            >
              ◎ 哒 · 鼓边
            </button>
          </div>
          <p role="status">{rhythmMessage || '听一遍示范，再照着敲。没有时间限制。'}</p>
        </div>
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
