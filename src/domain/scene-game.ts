/** Pure scene physics. A missed motor action never emits a learning answer. */
import { gameCatalog } from './games';
export type Scene = 'runner' | 'boat' | 'drum' | 'space';
export type Level = keyof typeof gameCatalog.levels;
export type Speed = keyof typeof gameCatalog.speeds;
export type GameSettings = {
  version: number;
  level: Level;
  speed: Speed;
  requestedDifficulty: Level | 'auto';
  requestedSpeed: Speed | 'auto';
  recommendation: {
    level: Level;
    speed: Speed;
    sampleSize: number;
    correctCount: number;
    masteredCount: number;
  };
};
export type Action = 'left' | 'right' | 'act' | 'pass';
export type World = {
  time: number;
  x: number;
  vx: number;
  distance: number;
  jump: number;
  jumpVelocity: number;
  note: number;
  shot: { x: number; y: number } | null;
  hit: number | null;
  misses: number;
  strokes: number;
  lastStroke: -1 | 0 | 1;
};
export const initialWorld = (): World => ({
  time: 0,
  x: 400,
  vx: 0,
  distance: 0,
  jump: 0,
  jumpVelocity: 0,
  note: 0,
  shot: null,
  hit: null,
  misses: 0,
  strokes: 0,
  lastStroke: 0,
});
export const laneX = (index: number, count: number) => 120 + index * (560 / Math.max(1, count - 1));
export function targetPosition(
  scene: Scene,
  index: number,
  count: number,
  world: World,
  level: Level,
) {
  const x = laneX(index, count);
  if (scene === 'runner') return { x, y: 110 + world.distance };
  if (scene === 'boat')
    return {
      x: x + Math.sin(world.time * 0.7 + index) * (level === 'challenge' ? 22 : 8),
      y: 100 + world.distance,
    };
  if (scene === 'drum') return { x: 180 + index * 200 - world.distance, y: 190 };
  return {
    x:
      x +
      Math.sin(world.time * 0.8 + index) *
        (level === 'challenge' ? 48 : level === 'steady' ? 24 : 0),
    y: 120 + Math.sin(world.time + index) * 12,
  };
}
export function advanceWorld(
  prior: World,
  seconds: number,
  scene: Scene,
  count: number,
  level: Level,
  speed: Speed,
  assist: boolean,
  action?: Action,
): World {
  if (prior.hit !== null) return prior;
  const w: World = { ...prior, shot: prior.shot ? { ...prior.shot } : null };
  const config = gameCatalog.levels[level];
  const slow = assist || config.assist;
  const dt = Math.max(0, Math.min(0.05, seconds));
  const motion = gameCatalog.speeds[speed].factor * (assist ? 0.45 : 1);
  w.time += dt * motion;
  if (scene === 'runner') {
    if (action === 'left' || action === 'right') {
      const nearest = Math.round((w.x - 120) / (560 / Math.max(1, count - 1)));
      w.x = laneX(Math.max(0, Math.min(count - 1, nearest + (action === 'left' ? -1 : 1))), count);
    }
    // Root lies before the gates; easy mode waits here for a jump.
    const previousDistance = w.distance;
    w.distance += dt * config.travel * motion;
    if (slow && w.distance >= 145 && w.jump <= 0 && previousDistance <= 145) w.distance = 145;
    if (action === 'act' && w.jump <= 0) {
      w.jumpVelocity = 380;
      w.jump = 1;
    }
    if (w.jump > 0) {
      w.jumpVelocity -= 650 * dt * motion;
      w.jump = Math.max(0, w.jump + w.jumpVelocity * dt * motion);
    }
    if (previousDistance < 170 && w.distance >= 170 && w.jump < 12)
      return { ...initialWorld(), x: w.x, misses: w.misses + 1, time: w.time };
    if (w.distance >= 240) {
      w.hit = Math.max(
        0,
        Math.min(count - 1, Math.round((w.x - 120) / (560 / Math.max(1, count - 1)))),
      );
    }
  } else if (scene === 'boat') {
    if (action === 'left' || action === 'right') {
      const direction = action === 'left' ? -1 : 1;
      w.vx += direction * 90;
      // Alternating strokes move the boat farther; same-side strokes steer.
      w.distance += w.lastStroke !== direction ? 28 : 10;
      w.lastStroke = direction;
      w.strokes++;
    }
    if (action === 'act') {
      w.distance += 24;
      w.strokes += 2;
    }
    w.vx += Math.sin(w.time) * (level === 'challenge' ? 35 : level === 'steady' ? 15 : 0) * dt;
    w.x += w.vx * dt * motion;
    w.vx *= Math.exp(-1.3 * dt * motion);
    if (w.x < 75 || w.x > 725) {
      w.x = Math.max(75, Math.min(725, w.x));
      w.vx *= -0.3;
    }
    if (w.distance >= 245) {
      const target = Array.from({ length: count }, (_, i) => ({
        i,
        p: targetPosition(scene, i, count, w, level),
      })).find((t) => Math.abs(t.p.x - w.x) < config.targetRadius + 22);
      if (target) w.hit = target.i;
      else {
        w.distance = 160;
        w.misses++;
      }
    }
  } else if (scene === 'drum') {
    const nextAt = w.note * 200;
    w.distance += dt * config.travel * motion;
    if (slow && w.distance >= nextAt) w.distance = nextAt;
    if (action === 'pass') {
      w.note = (w.note + 1) % count;
      w.distance = w.note === 0 ? -120 : w.distance;
    }
    if (action === 'act') {
      const candidate = Array.from({ length: count }, (_, i) => i).find(
        (i) => Math.abs(180 + i * 200 - w.distance - 180) <= config.targetRadius,
      );
      if (candidate !== undefined) w.hit = candidate;
      else w.misses++;
    }
    if (!slow && w.distance > nextAt + config.targetRadius + 15) w.note++;
    if (w.note >= count || w.distance > count * 200) {
      w.note = 0;
      w.distance = -120;
    }
  } else {
    if (action === 'left' || action === 'right')
      w.x = Math.max(80, Math.min(720, w.x + (action === 'left' ? -28 : 28)));
    if (action === 'act' && !w.shot) w.shot = { x: w.x, y: 350 };
    if (w.shot) {
      w.shot.y -= dt * 240 * motion;
      const hit = Array.from({ length: count }, (_, i) => ({
        i,
        p: targetPosition(scene, i, count, w, level),
      })).find((t) => Math.hypot(t.p.x - w.shot!.x, t.p.y - w.shot!.y) < config.targetRadius + 10);
      if (hit) w.hit = hit.i;
      else if (w.shot.y < 30) {
        w.shot = null;
        w.misses++;
      }
    }
  }
  return w;
}
