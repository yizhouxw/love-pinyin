import type { Scene, World, Level } from '../domain/scene-game';
import { gameCatalog } from '../domain/games';
import { targetPosition } from '../domain/scene-game';
import type { Option } from '../domain/learning-api';

function Fox({ x, y, jump = 0 }: { x: number; y: number; jump?: number }) {
  return (
    <g transform={`translate(${x} ${y - jump})`}>
      <ellipse cy="27" rx="23" ry="8" fill="#163b3933" />
      <path d="M-18 0Q-43-20-43 5Q-30 25-15 14" fill="#e98742" />
      <path d="M-21-24L-24-53-3-39 17-53 21-20Q25 9 0 13Q-29 7-21-24" fill="#ed9952" />
      <path d="M-20-18L0-3 20-18Q19 9 0 12Q-19 8-20-18" fill="#fff4d3" />
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
  level,
  highlight,
}: {
  scene: Scene;
  world: World;
  options: Option[];
  level: Level;
  highlight?: string;
}) {
  const offset = world.distance % 70;
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
          <stop
            stopColor={scene === 'space' ? '#15264f' : scene === 'drum' ? '#f9d3a0' : '#d7f0dd'}
          />
          <stop
            offset="1"
            stopColor={scene === 'space' ? '#424986' : scene === 'boat' ? '#91d5d6' : '#fcf0cf'}
          />
        </linearGradient>
        <linearGradient id="scene-river" x2="1" y2="1">
          <stop stopColor="#55c2cc" />
          <stop offset="1" stopColor="#3098ae" />
        </linearGradient>
      </defs>
      <rect width="800" height="440" rx="24" fill="url(#scene-sky)" />
      {scene === 'runner' && (
        <>
          <circle cx="660" cy="65" r="35" fill="#fff5b4" />
          <path d="M0 160Q120 25 240 135Q390 25 530 145Q680 25 800 125V440H0" fill="#95bc8f" />
          <path d="M80 440L205 110H595L720 440Z" fill="#d8b681" />
          {options.map((_, i) => (
            <path
              key={i}
              d={`M${120 + (i * 560) / Math.max(1, options.length - 1)} 130V440`}
              stroke="#f6e7b1"
              strokeWidth="3"
              strokeDasharray="20 18"
              strokeDashoffset={-offset}
            />
          ))}
          {[0, 1, 2, 3, 4].map((i) => (
            <g
              key={i}
              transform={`translate(${i % 2 ? 740 : 40} ${((i * 100 + world.distance * 0.7) % 480) - 30})`}
            >
              <path d="M0-60L-35 12H35Z" fill={i % 2 ? '#397f61' : '#4c9d68'} />
              <path d="M0 5V40" stroke="#986d46" strokeWidth="9" />
            </g>
          ))}
          <path
            d={`M95 ${180 + world.distance}Q400 ${162 + world.distance} 705 ${180 + world.distance}`}
            stroke="#ac7946"
            strokeWidth="15"
            fill="none"
          />
        </>
      )}
      {scene === 'boat' && (
        <>
          <path
            d="M0 100Q110 40 215 100L135 440H0M800 100Q690 40 585 100L665 440H800"
            fill="#72ac74"
          />
          <path d="M90 85Q400 45 710 85L750 440H50Z" fill="url(#scene-river)" />
          {[0, 1, 2, 3, 4, 5].map((i) => (
            <path
              key={i}
              d={`M${210 + (i % 2) * 100} ${(i * 83 + world.time * 35) % 440}q55-15 110 0t110 0`}
              stroke="#b9eff0"
              strokeWidth="4"
              opacity=".6"
              fill="none"
            />
          ))}
          <g transform="translate(60 220)">
            <ellipse rx="34" ry="15" fill="#3d9876" />
            <path d="M-10 0L0-38 10 0" fill="#f8b3b1" />
          </g>
        </>
      )}
      {scene === 'drum' && (
        <>
          <circle cx="650" cy="75" r="40" fill="#fff1c2" />
          <path d="M0 330Q120 280 240 340T480 340T800 330V440H0" fill="#81bca9" />
          {[70, 300, 530, 750].map((x) => (
            <g key={x}>
              <path d={`M${x} 40V120`} stroke="#a25e55" strokeWidth="2" />
              <ellipse cx={x} cy="115" rx="27" ry="33" fill="#df735e" />
              <path d={`M${x - 15} 115h30`} stroke="#f8d998" strokeWidth="4" />
            </g>
          ))}
          <rect x="45" y="147" width="710" height="91" rx="43" fill="#4e425c" />
          <path d="M180 138V250" stroke="#ffdf81" strokeWidth="8" />
          <circle cx="180" cy="190" r="44" fill="#fff1c233" stroke="#ffdf81" strokeWidth="3" />
          <g transform="translate(180 352)">
            <ellipse rx="77" ry="31" fill="#a94b50" />
            <path d="M-77-43V0Q0 45 77 0V-43" fill="#dc7562" />
            <ellipse cy="-43" rx="77" ry="31" fill="#fff0c6" stroke="#a94b50" strokeWidth="7" />
            <path
              d="M-50-20L-80-65M50-20L80-65"
              stroke="#72523d"
              strokeWidth="9"
              strokeLinecap="round"
            />
          </g>
          <Fox x={640} y={355} />
        </>
      )}
      {scene === 'space' && (
        <>
          {Array.from({ length: 32 }, (_, i) => (
            <circle
              key={i}
              cx={(i * 137) % 800}
              cy={(i * 71) % 440}
              r={i % 3 === 0 ? 2 : 1}
              fill="#e7e7ff"
              opacity=".7"
            />
          ))}
          <ellipse
            cx="660"
            cy="360"
            rx="100"
            ry="29"
            fill="#777db0"
            transform="rotate(-20 660 360)"
          />
          <circle cx="660" cy="360" r="55" fill="#646fa5" />
          <path d={`M${world.x} 345V85`} stroke="#d6dcff66" strokeDasharray="6 9" strokeWidth="2" />
        </>
      )}
      {options.map((option, index) => {
        const p = targetPosition(scene, index, options.length, world, level),
          active = highlight === option.id;
        return (
          <g
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
                  r={gameCatalog.levels[level].targetRadius}
                  fill={
                    active ? '#f8d88e' : ['#dba9b6', '#9ecfcb', '#e5c59b', '#bac0ef'][index % 4]
                  }
                  stroke="#f3e5ce"
                  strokeWidth="4"
                />
                <ellipse
                  rx={gameCatalog.levels[level].targetRadius + 14}
                  ry="12"
                  fill="none"
                  stroke="#f3e5ce"
                  strokeWidth="3"
                  transform="rotate(-20)"
                />
              </>
            ) : (
              <circle
                r={gameCatalog.levels[level].targetRadius}
                fill={active ? '#fce191' : index % 2 ? '#98d7dc' : '#f4bfb0'}
                stroke="#fff0d1"
                strokeWidth="4"
              />
            )}
            <text
              y="9"
              textAnchor="middle"
              className="scene-pinyin"
              fontSize={option.label.length > 6 ? 21 : 35}
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
    </svg>
  );
}
