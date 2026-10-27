import type { Scene, World } from '../domain/scene-game';
import type { RouteTheme } from '../domain/game-levels';

function Tree({ x, y, scale = 1, color }: { x: number; y: number; scale?: number; color: string }) {
  return (
    <g transform={`translate(${x} ${y}) scale(${scale})`}>
      <ellipse cy="45" rx="34" ry="10" fill="#183e3622" />
      <path d="M-5 0L-9 45H9L5 0" fill="#8c6949" />
      <path d="M0-75Q-49-44-30-13Q-60 15-25 27Q-5 42 16 25Q60 30 35-9Q52-40 0-75" fill={color} />
      <path
        d="M-15-42Q-30-25-20-10"
        fill="none"
        stroke="#ffffff22"
        strokeWidth="9"
        strokeLinecap="round"
      />
    </g>
  );
}

/** Decorative local vector scenery. Physics and teaching targets stay in SceneWorld. */
export function SceneScenery({
  scene,
  theme,
  world,
  routeOffset,
  count,
  scenery,
}: {
  scene: Scene;
  theme: RouteTheme;
  world: World;
  routeOffset: number;
  count: number;
  scenery: number;
}) {
  const offset = (world.distance + routeOffset) % 70;
  return (
    <g aria-hidden="true">
      <defs>
        <linearGradient id="trail" x2="0" y2="1">
          <stop stopColor="#f3e2b5" />
          <stop offset="1" stopColor="#d7ab77" />
        </linearGradient>
        <linearGradient id="water" x2="0.5" y2="1">
          <stop stopColor={theme.horizon} />
          <stop offset=".35" stopColor="#76d0d0" />
          <stop offset="1" stopColor="#298fa8" />
        </linearGradient>
        <radialGradient id="nebula">
          <stop stopColor={theme.accent} stopOpacity=".45" />
          <stop offset="1" stopColor={theme.sky} stopOpacity="0" />
        </radialGradient>
        <linearGradient id="track">
          <stop stopColor="#473d64" />
          <stop offset="1" stopColor="#262d52" />
        </linearGradient>
      </defs>
      {scene !== 'space' && (
        <>
          <circle cx={scenery % 2 ? 666 : 110} cy="68" r="47" fill="#fff4c5" opacity=".35" />
          <circle cx={scenery % 2 ? 666 : 110} cy="68" r="31" fill="#fff4c5" />
          {[140, 395, 710].map((x, i) => (
            <g
              key={x}
              transform={`translate(${x - ((world.distance * 0.025) % 100)} ${43 + i * 19})`}
              fill="#fffdf2"
              opacity=".65"
            >
              <ellipse rx="44" ry="12" />
              <ellipse cx="-13" cy="-9" rx="20" ry="17" />
              <ellipse cx="13" cy="-5" rx="25" ry="16" />
            </g>
          ))}
        </>
      )}
      {scene === 'runner' && (
        <>
          <path
            d="M0 144Q100 54 200 130Q310 35 420 127Q580 42 800 120V440H0Z"
            fill={theme.land}
            opacity=".55"
          />
          <path d="M0 188Q80 90 230 176Q410 70 550 166Q680 90 800 160V440H0Z" fill={theme.land} />
          {[35, 95, 710, 775].map((x, i) => (
            <Tree
              key={x}
              x={x}
              y={156 + (i % 2) * 20}
              scale={0.8}
              color={i % 2 ? '#5c9976' : '#39765e'}
            />
          ))}
          <path d="M65 440L186 156Q400 128 614 156L735 440Z" fill="url(#trail)" />
          <path d="M67 440L190 157M733 440L610 157" stroke="#f8ecc4" strokeWidth="8" fill="none" />
          {Array.from({ length: count }, (_, i) => (
            <path
              key={i}
              d={`M${120 + (i * 560) / Math.max(1, count - 1)} 158V440`}
              stroke="#fff2cb"
              strokeWidth="3"
              strokeDasharray="14 22"
              strokeDashoffset={-offset}
              opacity=".65"
            />
          ))}
          {[0, 1, 2, 3].map((i) => (
            <g
              key={i}
              transform={`translate(${i % 2 ? 767 : 29} ${170 + ((i * 115 + world.distance * 0.3) % 300)})`}
            >
              <Tree x={0} y={0} scale={1.1} color={i % 2 ? '#316c56' : '#478666'} />
              <path d="M-16 55v16M-28 60h24" stroke="#f5d9ae" strokeWidth="7" />
              <path d="M-36 58Q-17 30 3 58Z" fill={theme.accent} />
              <circle cx="-20" cy="51" r="3" fill="#fff6df" />
            </g>
          ))}
          {scenery >= 3 && (
            <g transform="translate(659 138)">
              <path d="M-14 15L-9-48H9L14 15Z" fill="#f3e9bf" />
              <path d="M-17-47L0-64 17-47Z" fill={theme.accent} />
              <path
                d={`M0-32l${scenery * 3} -20M0-32l-22 15M0-32l22 15`}
                stroke="#f1dfa9"
                strokeWidth="6"
              />
            </g>
          )}
        </>
      )}
      {scene === 'boat' && (
        <>
          <path
            d="M0 136Q130 56 250 123Q420 55 580 130Q700 65 800 125V440H0Z"
            fill={theme.land}
            opacity=".5"
          />
          <path
            d="M0 153Q100 100 211 154L113 440H0M800 153Q695 100 589 154L687 440H800"
            fill={theme.land}
          />
          <path d="M183 142Q400 113 617 142L754 440H46Z" fill="url(#water)" />
          <path d="M184 143L46 440M616 143L754 440" stroke="#c5e9c2" strokeWidth="7" opacity=".7" />
          {Array.from({ length: 12 }, (_, i) => (
            <path
              key={i}
              d={`M${135 + (i % 4) * 150} ${155 + ((i * 29 + world.distance * 0.4) % 280)}q20-7 40 0t40 0`}
              stroke="#d8ffff"
              strokeWidth={i % 2 ? 2 : 3}
              opacity=".4"
              fill="none"
            />
          ))}
          {[30, 105, 700, 775].map((x, i) => (
            <Tree key={x} x={x} y={174 + (i % 2) * 45} scale={0.8} color="#5a9d7b" />
          ))}
          {[0, 1, 2, 3].map((i) => (
            <g
              key={i}
              transform={`translate(${i % 2 ? 700 : 90} ${245 + ((i * 57 + world.distance * 0.2) % 150)})`}
            >
              <ellipse rx="26" ry="9" fill="#378f72" />
              <path d="M-16 0Q-20-22 0-9Q20-25 16 0Z" fill="#f2b7bb" />
              <path d="M-2-3V-14" stroke="#ffe3b0" strokeWidth="3" />
            </g>
          ))}
          {scenery >= 3 && (
            <g transform="translate(655 150)">
              <path d="M-18 15L-11-49H11L18 15Z" fill="#fff1cc" />
              <path d="M-15-40H15M-13-22H13" stroke={theme.accent} strokeWidth="10" />
              <path d="M-20-50L0-67 20-50Z" fill="#477770" />
            </g>
          )}
        </>
      )}
      {scene === 'drum' && (
        <>
          <path
            d="M0 310Q130 225 250 304Q390 225 540 302Q690 220 800 294V440H0Z"
            fill={theme.land}
          />
          <path d="M0 357Q400 308 800 357V440H0Z" fill="#cc9c79" />
          <path d="M0 390Q400 345 800 390" stroke="#edc499" strokeWidth="4" fill="none" />
          <path d="M0 32Q400 105 800 32" fill="none" stroke="#9e6f60" strokeWidth="3" />
          {[55, 170, 285, 400, 515, 630, 745].map((x, i) => (
            <g key={x} transform={`translate(${x} ${45 + Math.sin(i / 2) * 24})`}>
              <path d="M-17 0H17L0 28Z" fill={i % 2 ? theme.accent : '#fff0bd'} />
              <path d="M0 0V39" stroke="#9e6f60" strokeWidth="2" />
              <ellipse cy="51" rx="16" ry="21" fill={i % 2 ? '#e7a35f' : '#de7e79'} />
              <path d="M-10 51h20" stroke="#ffe5a3" strokeWidth="3" />
            </g>
          ))}
          <rect x="35" y="139" width="730" height="106" rx="53" fill="#f5d9a0" />
          <rect x="42" y="146" width="716" height="92" rx="46" fill="url(#track)" />
          <path d="M70 191H734" stroke="#bfb5d2" strokeWidth="2" strokeDasharray="4 12" />
          <path d="M180 134V250" stroke="#ffe4a0" strokeWidth="7" />
          <circle cx="180" cy="190" r="44" fill="#fff1c222" stroke="#ffe4a0" strokeWidth="3" />
          <g transform="translate(180 355)">
            <ellipse cy="17" rx="95" ry="20" fill="#7c524e33" />
            <path d="M-77-43V0Q0 45 77 0V-43" fill="#c96d62" />
            {[-50, -25, 0, 25, 50].map((x) => (
              <path key={x} d={`M${x} -30v42`} stroke="#f4d6a0" strokeWidth="3" />
            ))}
            <ellipse cy="-43" rx="77" ry="31" fill="#fff0c6" stroke="#a94b50" strokeWidth="7" />
            <ellipse cy="-43" rx="60" ry="22" fill="none" stroke="#dcc28b" strokeWidth="2" />
            <path
              d={`M-50-20L-80 ${world.flash > 0 ? -28 : -65}M50-20L80 ${world.flash > 0 ? -28 : -65}`}
              stroke="#72523d"
              strokeWidth="9"
              strokeLinecap="round"
            />
          </g>
          <path
            d="M500 365q-20-20 0-40q20 20 0 40M550 375q-20-20 0-40q20 20 0 40M720 365q-20-20 0-40q20 20 0 40"
            fill={theme.accent}
            opacity=".6"
          />
        </>
      )}
      {scene === 'space' && (
        <>
          <ellipse
            cx="500"
            cy="140"
            rx="450"
            ry="240"
            fill="url(#nebula)"
            transform="rotate(-20 500 140)"
          />
          <path
            d="M30 340Q300 20 770 100M90 440Q440 70 800 210"
            stroke="#b9b1f5"
            opacity=".15"
            fill="none"
            strokeWidth="2"
          />
          {Array.from({ length: 60 }, (_, i) => (
            <circle
              key={i}
              cx={(i * 137 + scenery * 19) % 800}
              cy={(i * 79 + world.distance * ((i % 3) + 1) * 0.035) % 440}
              r={i % 7 ? 1.2 : 2.5}
              fill={i % 2 ? '#fff0ca' : '#ced7ff'}
              opacity={0.35 + (i % 4) * 0.15}
            />
          ))}
          <path
            d="M70 75L145 49 217 98 290 55M145 49L175 137"
            stroke="#d3c7ff"
            fill="none"
            opacity=".25"
          />
          <circle cx="660" cy="365" r="60" fill="#787cb0" />
          <path
            d="M611 330Q669 335 703 393M608 347Q660 354 690 409"
            stroke="#9b98c6"
            strokeWidth="9"
            opacity=".6"
            fill="none"
          />
          <ellipse
            cx="660"
            cy="365"
            rx="100"
            ry="23"
            fill="none"
            stroke={theme.accent}
            strokeWidth="9"
            opacity=".65"
            transform="rotate(-22 660 365)"
          />
          <path
            d={`M${world.x} 335V163`}
            stroke="#d6dcff55"
            strokeDasharray="4 10"
            strokeWidth="2"
          />
        </>
      )}
    </g>
  );
}
