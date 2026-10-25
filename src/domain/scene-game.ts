/** Pure mechanics: route data + input + time -> world. No content or UI imports. */
import type { RoutePattern } from './game-levels';
export type Scene = 'runner' | 'boat' | 'drum' | 'space';
export type Level = 'gentle' | 'steady' | 'challenge';
export type Speed = 'slow' | 'normal' | 'fast';
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
export type EngineConfig = {
  pattern: RoutePattern;
  count: number;
  travel: number;
  assist: boolean;
  targetRadius: number;
  speedFactor: number;
  targetMotion: number;
  currentScale: number;
};
export type World = {
  time: number;
  x: number;
  vx: number;
  distance: number;
  jump: number;
  jumpVelocity: number;
  forwardVelocity: number;
  note: number;
  shot: { x: number; y: number } | null;
  hit: number | null;
  misses: number;
  strokes: number;
  lastStroke: -1 | 0 | 1;
  cleared: string[];
  collected: string[];
  beatHits: number[];
  flash: number;
};
export const initialWorld = (): World => ({
  time: 0,
  x: 400,
  vx: 0,
  distance: 0,
  jump: 0,
  jumpVelocity: 0,
  forwardVelocity: 0,
  note: 0,
  shot: null,
  hit: null,
  misses: 0,
  strokes: 0,
  lastStroke: 0,
  cleared: [],
  collected: [],
  beatHits: [],
  flash: 0,
});
export const laneX = (i: number, count: number) => 120 + (i * 560) / Math.max(1, count - 1);
export const routeY = (at: number, w: World) => 365 - (at - w.distance) * 0.7;
export const routeX = (lane: number, count: number) =>
  laneX(((lane % count) + count) % count, count);
export function targetPosition(index: number, w: World, c: EngineConfig) {
  const scene = c.pattern.scene,
    x = laneX(index, c.count);
  if (scene === 'runner' || scene === 'boat')
    return {
      x: x + (scene === 'boat' ? Math.sin(w.time * 0.7 + index) * c.targetMotion : 0),
      y: routeY(c.pattern.choiceAt, w),
    };
  if (scene === 'drum')
    return { x: 180 + c.pattern.choiceAt + index * c.pattern.choiceGap - w.distance, y: 190 };
  return {
    x: x + Math.sin(w.time * 0.8 + index) * c.targetMotion,
    y: 120 + Math.sin(w.time + index) * 12,
  };
}
export function advanceWorld(
  prior: World,
  seconds: number,
  c: EngineConfig,
  action?: Action,
): World {
  if (prior.hit !== null) return prior;
  const w = {
    ...prior,
    shot: prior.shot ? { ...prior.shot } : null,
    cleared: [...prior.cleared],
    collected: [...prior.collected],
    beatHits: [...prior.beatHits],
  };
  const p = c.pattern,
    scene = p.scene,
    dt = Math.max(0, Math.min(0.05, seconds)),
    motion = c.speedFactor,
    travel = c.travel * p.travelScale;
  w.time += dt * motion;
  w.flash = Math.max(0, w.flash - dt);
  const previous = w.distance;
  if (scene === 'runner') {
    if (action === 'left' || action === 'right')
      w.x = laneX(
        Math.max(
          0,
          Math.min(
            c.count - 1,
            Math.round((w.x - 120) / (560 / Math.max(1, c.count - 1))) +
              (action === 'left' ? -1 : 1),
          ),
        ),
        c.count,
      );
    if (action === 'act' && w.jump <= 0) {
      w.jump = 1;
      w.jumpVelocity = 380;
    }
    if (w.jump > 0) {
      w.jumpVelocity -= 650 * dt * motion;
      w.jump = Math.max(0, w.jump + w.jumpVelocity * dt * motion);
    }
    w.distance += dt * travel * motion;
  } else if (scene === 'boat') {
    if (action === 'left' || action === 'right') {
      const dir = action === 'left' ? -1 : 1;
      w.vx += dir * 100;
      w.forwardVelocity += w.lastStroke !== dir ? 100 : 60;
      w.lastStroke = dir;
      w.strokes++;
    }
    if (action === 'act') {
      w.forwardVelocity += 100;
      w.strokes += 2;
    }
    w.forwardVelocity = Math.min(travel * 2, w.forwardVelocity);
    w.distance += w.forwardVelocity * dt * motion;
    w.forwardVelocity *= Math.exp(-0.7 * dt * motion);
    w.vx += Math.sin(w.time) * p.currentStrength * c.currentScale * dt;
    w.x = Math.max(75, Math.min(725, w.x + w.vx * dt * motion));
    w.vx *= Math.exp(-1.8 * dt * motion);
  } else if (scene === 'drum') {
    w.distance += dt * travel * motion;
    const at = p.choiceAt + w.note * p.choiceGap;
    if (c.assist && w.distance >= at) w.distance = at;
    if (action === 'pass') {
      w.note++;
      if (w.note >= c.count) {
        w.note = 0;
        w.distance = p.choiceAt - p.choiceGap;
      }
    }
    if (action === 'act') {
      const index = Array.from({ length: c.count }, (_, i) => i).find(
        (i) => Math.abs(p.choiceAt + i * p.choiceGap - w.distance) <= c.targetRadius,
      );
      if (index !== undefined) w.hit = index;
      else {
        const beat = p.beats.find(
          (t) => Math.abs(t - w.distance) <= c.targetRadius && !w.beatHits.includes(t),
        );
        if (beat !== undefined) {
          w.beatHits.push(beat);
          w.flash = 0.25;
        } else w.misses++;
      }
    }
    if (!c.assist && w.distance > at + c.targetRadius + 25) w.note++;
    if (w.note >= c.count) {
      w.note = 0;
      w.distance = p.choiceAt - p.choiceGap;
    }
  } else {
    if (action === 'left' || action === 'right')
      w.x = Math.max(80, Math.min(720, w.x + (action === 'left' ? -28 : 28)));
    if (action === 'act' && !w.shot) w.shot = { x: w.x, y: 350 };
    w.distance = Math.min(p.choiceAt, w.distance + dt * travel * motion);
    if (w.shot) {
      w.shot.y -= dt * 260 * motion;
      const rock = p.obstacles.find(
        (o) =>
          !w.cleared.includes(o.id) &&
          Math.hypot(routeX(o.lane, c.count) - w.shot!.x, routeY(o.at, w) - w.shot!.y) <
            o.size + 12,
      );
      if (rock) {
        w.cleared.push(rock.id);
        w.shot = null;
        w.flash = 0.3;
      } else if (w.distance >= p.choiceAt) {
        const hit = Array.from({ length: c.count }, (_, i) => ({
          i,
          pos: targetPosition(i, w, c),
        })).find((t) => Math.hypot(t.pos.x - w.shot!.x, t.pos.y - w.shot!.y) < c.targetRadius + 10);
        if (hit) w.hit = hit.i;
      }
      if (w.shot && w.shot.y < 10) {
        w.shot = null;
        w.misses++;
      }
    }
  }
  if (scene !== 'drum') {
    for (const obstacle of p.obstacles) {
      if (w.cleared.includes(obstacle.id)) continue;
      const aligned =
        obstacle.lane === -1 || Math.abs(routeX(obstacle.lane, c.count) - w.x) < obstacle.size + 25;
      const jumping = scene === 'runner' && obstacle.kind === 'root' && w.jump > 15;
      if (
        c.assist &&
        aligned &&
        !jumping &&
        previous <= obstacle.at - 25 &&
        w.distance >= obstacle.at - 25
      )
        w.distance = obstacle.at - 25;
      if (previous < obstacle.at && w.distance >= obstacle.at) {
        if (aligned && !jumping) {
          w.distance = obstacle.at - 55;
          w.forwardVelocity = 0;
          w.misses++;
          w.flash = 0.3;
        } else w.cleared.push(obstacle.id);
      }
    }
    for (const pickup of p.pickups)
      if (
        !w.collected.includes(pickup.id) &&
        previous < pickup.at &&
        w.distance >= pickup.at &&
        Math.abs(routeX(pickup.lane, c.count) - w.x) < 52
      ) {
        w.collected.push(pickup.id);
        w.flash = 0.25;
      }
    if ((scene === 'runner' || scene === 'boat') && w.distance >= p.choiceAt) {
      const hit = Array.from({ length: c.count }, (_, i) => ({
        i,
        pos: targetPosition(i, w, c),
      })).find((t) => Math.abs(t.pos.x - w.x) < c.targetRadius + 22);
      if (hit) w.hit = hit.i;
      else {
        w.distance = p.choiceAt - 65;
        w.misses++;
      }
    }
  }
  return w;
}
