import type { Scene, World, EngineConfig } from '../domain/scene-game';
import type { RouteTheme } from '../domain/game-levels';
import { targetPosition, routeX, routeY } from '../domain/scene-game';
import type { Option } from '../domain/learning-api';
import { SceneScenery } from './scene-scenery';

/** Original explorer character; rendered locally at every display scale. */
function Fox({ x, y, jump = 0 }: { x: number; y: number; jump?: number }) {
  return (
    <g transform={`translate(${x} ${y - jump})`}>
      <ellipse cy={29 + jump} rx={25 - Math.min(10, jump / 10)} ry="7" fill="#244f3b30" />
      <path
        d="M-16 10C-52 22-64-12-49-25C-45-9-30-16-21-6Z"
        fill="#c96735"
        stroke="#994d32"
        strokeWidth="2"
      />
      <path d="M-49-25Q-45-9-34-10Q-40 3-51-1Q-57-13-49-25Z" fill="#fff1d5" />
      <path d="M-16 4Q0-5 17 4L18 21Q0 30-18 20Z" fill="#d9823e" />
      <path d="M-8 10Q0 4 9 10V23H-8Z" fill="#ffdfaf" />
      <path d="M-12 20L-15 30M12 20L16 30" stroke="#864934" strokeWidth="9" strokeLinecap="round" />
      <path
        d="M-25-17L-29-54Q-17-50-9-41Q0-44 10-41Q21-52 29-54L25-17Q22 6 0 10Q-24 5-25-17Z"
        fill="#ec9247"
        stroke="#b96235"
        strokeWidth="2"
      />
      <path d="M-25-47L-22-28-12-39M25-47L22-28 12-39" fill="#643f3d" />
      <path d="M-19-43L-18-32-12-38M19-43L18-32 12-38" fill="#efb3a0" />
      <path d="M-25-19Q-16-25 0-7Q16-25 25-19Q23 4 0 9Q-23 4-25-19Z" fill="#fff3d9" />
      <ellipse cx="-12" cy="-24" rx="3.5" ry="4.5" fill="#263f3e" />
      <ellipse cx="12" cy="-24" rx="3.5" ry="4.5" fill="#263f3e" />
      <circle cx="-13" cy="-25" r="1.2" fill="white" />
      <circle cx="11" cy="-25" r="1.2" fill="white" />
      <ellipse cx="-18" cy="-12" rx="4" ry="2" fill="#f2b394" />
      <ellipse cx="18" cy="-12" rx="4" ry="2" fill="#f2b394" />
      <path d="M-4-7Q0-10 4-7L0-3Z" fill="#2b4240" />
      <path
        d="M0-3V0Q4 3 7-1M0 0Q-4 3-7-1"
        fill="none"
        stroke="#9b674b"
        strokeWidth="1.5"
        strokeLinecap="round"
      />
      <path d="M-19 5Q0 14 20 5L18 13Q0 20-18 12Z" fill="#3f8b7b" />
      <path d="M14 10L28 18 17 24 9 13Z" fill="#367569" />
      <path d="M-17 12L-25 20M17 12L24 19" stroke="#e8a15d" strokeWidth="7" strokeLinecap="round" />
      <path
        d="M-4-36Q0-39 4-36"
        stroke="#ffd3a1"
        strokeWidth="3"
        fill="none"
        strokeLinecap="round"
      />
    </g>
  );
}
export function SceneWorld({
  scene,
  world,
  options,
  config,
  theme,
  routeOffset,
  scenery,
  highlight,
}: {
  scene: Scene;
  world: World;
  options: Option[];
  config: EngineConfig;
  theme: RouteTheme;
  routeOffset: number;
  scenery: number;
  highlight?: string;
}) {
  const pattern = config.pattern;
  return (
    <svg
      className={`scene-world world-${scene}`}
      viewBox="0 0 800 440"
      role="img"
      aria-label={
        {
          runner: '森林跑道：换道跳跃穿过拼音拱门',
          boat: '河湾：划桨控制小船驶进拼音浮标',
          drum: '鼓岛：移动的拼音音符与击打线',
          space: '星空：飞行包裹与移动的拼音星球',
        }[scene]
      }
    >
      <defs>
        <linearGradient id="scene-sky" x2="0" y2="1">
          <stop stopColor={theme.sky} />
          <stop offset="1" stopColor={theme.horizon} />
        </linearGradient>
        <linearGradient id="scene-river" x2="1" y2="1">
          <stop stopColor="#55c2cc" />
          <stop offset="1" stopColor="#3098ae" />
        </linearGradient>
      </defs>
      <rect width="800" height="440" rx="24" fill="url(#scene-sky)" />
      <SceneScenery
        scene={scene}
        theme={theme}
        world={world}
        routeOffset={routeOffset}
        count={options.length}
        scenery={scenery}
      />
      {scene === 'runner' && (
        <g opacity=".6" aria-hidden="true">
          <ellipse cx={world.x} cy="398" rx="42" ry="12" fill="#fff6c1" />
          <path
            d={`M${world.x - 18} 416l18 -8 18 8`}
            fill="none"
            stroke="#fff8d6"
            strokeWidth="5"
            strokeLinecap="round"
          />
        </g>
      )}
      {scene === 'boat' && (
        <g fill="none" stroke="#e4fff6" opacity=".65" aria-hidden="true">
          <path
            d={`M${world.x - 35} 393q35 12 70 0M${world.x - 48} 407q48 16 96 0`}
            strokeWidth="3"
          />
        </g>
      )}
      {scene === 'drum' && <Fox x={640} y={355} />}
      {scene === 'drum' &&
        pattern.beats.map((at) => {
          const x = 180 + at - world.distance;
          return (
            <g key={at} transform={`translate(${x} 190)`}>
              <circle
                r="22"
                fill={world.beatHits.includes(at) ? '#fff3ab' : theme.accent}
                stroke="#fff6d7"
                strokeWidth="3"
              />
              <text textAnchor="middle" y="8" fontSize="25" fill="#6e5345">
                {world.beatHits.includes(at) ? '✦' : '♪'}
              </text>
            </g>
          );
        })}
      {pattern.obstacles
        .filter((o) => !world.cleared.includes(o.id))
        .map((o) => {
          const x = o.lane === -1 ? 400 : routeX(o.lane, options.length),
            y = routeY(o.at, world);
          return (
            <g
              key={o.id}
              transform={`translate(${x} ${y})`}
              data-obstacle={o.id}
              data-obstacle-at={o.at}
              data-obstacle-lane={o.lane}
              data-obstacle-kind={o.kind}
            >
              {o.kind === 'root' ? (
                <>
                  <path
                    d={o.lane === -1 ? 'M-320 0Q0-15 320 0' : 'M-45 0Q0-15 45 0'}
                    stroke="#9b6946"
                    strokeWidth="20"
                    fill="none"
                  />
                  <path d="M-20-3L-33-24M20-5L34-20" stroke="#9b6946" strokeWidth="10" />
                </>
              ) : o.kind === 'bush' ? (
                <>
                  <ellipse rx="42" ry="27" fill="#477c55" />
                  <circle cx="-20" cy="-18" r="24" fill="#65975c" />
                  <circle cx="15" cy="-20" r="28" fill="#53884e" />
                </>
              ) : o.kind === 'reef' ? (
                <path
                  d="M-40 20L-24-20 0-37 28-16 42 20Z"
                  fill="#6f8190"
                  stroke="#4f6975"
                  strokeWidth="4"
                />
              ) : (
                <>
                  <path
                    d="M-35-12L-17-34 18-30 36-6 23 27-6 35-32 15Z"
                    fill="#8c839d"
                    stroke="#bfb0be"
                    strokeWidth="4"
                  />
                  <circle cx="-9" cy="-9" r="10" fill="#6e6c87" />
                  <circle cx="14" cy="10" r="7" fill="#6e6c87" />
                </>
              )}
            </g>
          );
        })}
      {pattern.pickups
        .filter((p) => !world.collected.includes(p.id))
        .map((p) => (
          <g
            key={p.id}
            transform={`translate(${routeX(p.lane, options.length)} ${routeY(p.at, world)})`}
          >
            <circle r="15" fill="#ffe29d" stroke="#c69246" strokeWidth="3" />
            <text y="6" textAnchor="middle" fontSize="18" fill="#986331">
              ✦
            </text>
          </g>
        ))}
      {options.map((option, index) => {
        const p = targetPosition(index, world, config),
          active = highlight === option.id;
        return (
          <g
            opacity={scene === 'space' && world.distance < pattern.choiceAt ? 0.8 : 1}
            key={option.id}
            transform={`translate(${p.x} ${p.y})`}
            data-scene-target={option.id}
            data-target-x={p.x}
            data-target-y={p.y}
            aria-label={`场景目标 ${option.label}`}
          >
            {scene === 'runner' ? (
              <>
                <path
                  d="M-48 55V-24Q0-80 48-24V55"
                  fill="#fff4cf"
                  stroke={active ? '#ecad26' : '#488269'}
                  strokeWidth="10"
                />
                <path d="M-55 55H55" stroke="#966a46" strokeWidth="8" />
                <path d="M-56-36Q0-91 56-36L49-26Q0-70-49-26Z" fill="#426e5b" />
                <circle cx="-47" cy="48" r="6" fill="#f8d285" />
                <circle cx="47" cy="48" r="6" fill="#f8d285" />
                <path
                  d="M-40-35q10-17 19-5M21-40q9-12 19 5"
                  fill="none"
                  stroke="#a9c882"
                  strokeWidth="5"
                />
              </>
            ) : scene === 'boat' ? (
              <>
                <ellipse
                  cy="34"
                  rx="62"
                  ry="15"
                  fill="none"
                  stroke="#e3fff0"
                  strokeWidth="3"
                  opacity=".7"
                />
                <ellipse cy="30" rx="57" ry="14" fill="#176b8044" />
                <path d="M0-39V-72l29 10-29 12" fill="#f4a36c" stroke="#956a45" strokeWidth="3" />
                <path
                  d="M-42 24L-31-37H31L42 24Z"
                  fill={active ? '#ffe07d' : '#ffefc6'}
                  stroke="#c47e4e"
                  strokeWidth="5"
                />
              </>
            ) : scene === 'space' ? (
              <>
                <circle
                  r={config.targetRadius}
                  fill={
                    active ? '#f8d88e' : ['#dba9b6', '#9ecfcb', '#e5c59b', '#bac0ef'][index % 4]
                  }
                  stroke="#f3e5ce"
                  strokeWidth="4"
                />
                <ellipse
                  rx={config.targetRadius + 14}
                  ry="12"
                  fill="none"
                  stroke="#f3e5ce"
                  strokeWidth="3"
                  transform="rotate(-20)"
                />
              </>
            ) : (
              <circle
                r={config.targetRadius}
                fill={active ? '#fce191' : index % 2 ? '#98d7dc' : '#f4bfb0'}
                stroke="#fff0d1"
                strokeWidth="4"
              />
            )}
            {(scene === 'runner' || scene === 'boat') && p.y > 270 && (
              <rect
                x="-52"
                y={238 - p.y}
                width="104"
                height="46"
                rx="14"
                fill="#fff4d5"
                stroke="#c6af79"
                strokeWidth="2"
              />
            )}
            <text
              y={scene === 'runner' || scene === 'boat' ? Math.min(9, 270 - p.y) : 9}
              textAnchor="middle"
              className="scene-pinyin"
              fontSize={option.label.length > 6 ? 24 : 39}
              fill="#263f48"
            >
              {option.label}
            </text>
            {active && (
              <text x="0" y="-60" textAnchor="middle" fontSize="26" fill="#e9a218">
                ✦
              </text>
            )}
          </g>
        );
      })}
      {scene === 'runner' && (
        <g className="scene-runner-position" style={{ transform: `translateX(${world.x}px)` }}>
          <Fox x={0} y={365} jump={world.jump} />
        </g>
      )}
      {scene === 'boat' && (
        <g transform={`translate(${world.x} 360) rotate(${world.vx / 12})`}>
          <path d="M-54 0Q0 65 54 0Z" fill="#ad6946" stroke="#6c543f" strokeWidth="5" />
          <path
            d={`M-15 0L-65 ${world.lastStroke === -1 ? 32 : -22}M15 0L65 ${world.lastStroke === 1 ? 32 : -22}`}
            stroke="#e6c997"
            strokeWidth="9"
            strokeLinecap="round"
          />
          <Fox x={0} y={-15} />
        </g>
      )}
      {scene === 'space' && (
        <g transform={`translate(${world.x} 370)`}>
          <path d="M-25 20L0-45 25 20 0 9Z" fill="#f8e9b8" stroke="#e5a485" strokeWidth="4" />
          <path
            d="M-17 8L-39 33-31-4-14-19M17 8L39 33 31-4 14-19"
            fill="#de937e"
            stroke="#f7cead"
            strokeWidth="3"
          />
          <circle cy="-10" r="12" fill="#315b7b" stroke="#fff6df" strokeWidth="3" />
          <path d="M-5-14q5-5 9 0" fill="none" stroke="#b4edf1" strokeWidth="3" />
          <path d="M-10 15h20" stroke="#c78470" strokeWidth="3" />
          <path d={`M-10 24L0 ${40 + Math.sin(world.time * 9) * 10} 10 24`} fill="#efa878" />
        </g>
      )}
      {world.shot && (
        <g transform={`translate(${world.shot.x} ${world.shot.y})`}>
          <path d="M0 0V25" stroke="#ffdda4" strokeWidth="5" />
          <rect x="-10" y="-10" width="20" height="20" rx="5" fill="#fff1c7" />
        </g>
      )}
      {world.flash > 0 && (
        <g
          transform={`translate(${scene === 'drum' ? 180 : world.x} ${scene === 'drum' ? 312 : 350})`}
          pointerEvents="none"
          opacity={Math.min(1, world.flash * 4)}
        >
          <ellipse
            rx={48 + (0.25 - Math.min(0.25, world.flash)) * 120}
            ry="32"
            fill="none"
            stroke="#fff0af"
            strokeWidth="4"
          />
          {[-1, 1].map((side) => (
            <path
              key={side}
              d={`M${side * 44} -35v-12m-6 6h12`}
              stroke="#fff6c9"
              strokeWidth="3"
              strokeLinecap="round"
            />
          ))}
        </g>
      )}
    </svg>
  );
}
