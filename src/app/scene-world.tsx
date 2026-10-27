import type { Scene, World, EngineConfig } from '../domain/scene-game';
import type { RouteTheme } from '../domain/game-levels';
import { targetPosition, routeX, routeY } from '../domain/scene-game';
import type { Option } from '../domain/learning-api';
import { SceneScenery } from './scene-scenery';

function Fox({ x, y, jump = 0 }: { x: number; y: number; jump?: number }) {
  return (
    <g transform={`translate(${x} ${y - jump})`}>
      <ellipse cy="27" rx="23" ry="8" fill="#163b3933" />
      <path d="M-18 0Q-43-20-43 5Q-30 25-15 14" fill="#e98742" />
      <path d="M-21-24L-24-53-3-39 17-53 21-20Q25 9 0 13Q-29 7-21-24" fill="#ed9952" />
      <path d="M-20-18L0-3 20-18Q19 9 0 12Q-19 8-20-18" fill="#fff4d3" />
      <path d="M-20-45L-17-32-8-39M17-45L14-32 5-39" fill="#764b41" />
      <path d="M-39 6Q-33 18-24 14L-31 5Z" fill="#fff4d3" />
      <ellipse cx="-14" cy="-13" rx="5" ry="3" fill="#ecb385" />
      <ellipse cx="14" cy="-13" rx="5" ry="3" fill="#ecb385" />
      <circle cx="-10" cy="-24" r="3" fill="#223d39" />
      <circle cx="10" cy="-24" r="3" fill="#223d39" />
      <path d="M-4-7L4-7 0-2Z" fill="#223d39" />
      <path d="M-12 13L-17 28M12 13L17 28" stroke="#a95634" strokeWidth="8" strokeLinecap="round" />
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
              </>
            ) : scene === 'boat' ? (
              <>
                <ellipse cy="30" rx="57" ry="14" fill="#176b8044" />
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
            <text
              y="9"
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
      {scene === 'runner' && <Fox x={world.x} y={365} jump={world.jump} />}
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
          <circle cy="-10" r="9" fill="#73b6c4" />
          <path d={`M-10 24L0 ${40 + Math.sin(world.time * 9) * 10} 10 24`} fill="#efa878" />
        </g>
      )}
      {world.shot && (
        <g transform={`translate(${world.shot.x} ${world.shot.y})`}>
          <path d="M0 0V25" stroke="#ffdda4" strokeWidth="5" />
          <rect x="-10" y="-10" width="20" height="20" rx="5" fill="#fff1c7" />
        </g>
      )}
      {world.hit !== null && (
        <g>
          <rect width="800" height="440" rx="24" fill="#fff4c433" />
          <text
            x="400"
            y="58"
            textAnchor="middle"
            fontSize="28"
            fill={scene === 'space' ? '#fff4c4' : '#294e45'}
          >
            ✦ 目标已抵达 ✦
          </text>
        </g>
      )}
      {world.flash > 0 && (
        <rect width="800" height="440" rx="24" fill="#ffe9a355" pointerEvents="none" />
      )}
    </svg>
  );
}
