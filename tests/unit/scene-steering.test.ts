import { expect, it } from 'vitest';
import { initialWorld, laneX } from '../../src/domain/scene-game';
import { steerWorld } from '../../src/domain/scene-steering';

it('touch steering reaches each lane and clamps overshooting gestures without answering', () => {
  for (const count of [2, 3, 4]) {
    for (let lane = 0; lane < count; lane++) {
      const world = steerWorld(initialWorld(), 'runner', count, laneX(lane, count));
      expect(world.x).toBe(laneX(lane, count));
      expect(world.hit).toBeNull();
      expect(world.distance).toBe(0);
    }
    expect(steerWorld(initialWorld(), 'runner', count, -300).x).toBe(laneX(0, count));
    expect(steerWorld(initialWorld(), 'runner', count, 1200).x).toBe(laneX(count - 1, count));
  }
});
it('direct steering stops sideways inertia but retains earned route state', () => {
  const world = {
    ...initialWorld(),
    vx: 100,
    forwardVelocity: 60,
    distance: 90,
    collected: ['star'],
  };
  const next = steerWorld(world, 'boat', 3, 500);
  expect(next).toEqual({ ...world, x: 500, vx: 0 });
  expect(world.vx).toBe(100);
  expect(steerWorld(world, 'space', 3, 900).x).toBe(720);
});
it('does not move pending answers, drum notes or invalid pointer input', () => {
  const world = initialWorld();
  expect(steerWorld(world, 'drum', 3, 700)).toBe(world);
  expect(steerWorld(world, 'boat', 3, NaN)).toBe(world);
  const pending = { ...world, hit: 1 };
  expect(steerWorld(pending, 'runner', 3, 700)).toBe(pending);
});
