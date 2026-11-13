import { laneX, type Scene, type World } from './scene-game';

/** Pointer steering never advances the route or commits a learning answer. */
export function steerWorld(world: World, scene: Scene, count: number, x: number): World {
  if (!Number.isFinite(x) || count < 1 || world.hit !== null || scene === 'drum') return world;
  const bounded = Math.max(80, Math.min(720, x));
  const lane = Math.max(
    0,
    Math.min(count - 1, Math.round(((bounded - 120) * Math.max(1, count - 1)) / 560)),
  );
  return { ...world, x: scene === 'runner' ? laneX(lane, count) : bounded, vx: 0 };
}
