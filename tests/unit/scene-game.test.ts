import { describe, expect, it } from 'vitest';
import {
  advanceWorld,
  initialWorld,
  laneX,
  targetPosition,
  type Scene,
  type World,
} from '../../src/domain/scene-game';
function ticks(
  w: World,
  seconds: number,
  scene: Scene,
  assist = false,
  speed: 'slow' | 'normal' | 'fast' = 'normal',
) {
  for (let i = 0; i < seconds * 100; i++)
    w = advanceWorld(w, 0.01, scene, 3, 'gentle', speed, assist);
  return w;
}
describe('SCENE physics, independent of learning answers', () => {
  it('runner waits at root, actual jump passes it, and the selected lane decides gate collision', () => {
    let w = ticks(initialWorld(), 8, 'runner');
    expect(w.distance).toBe(145);
    expect(w.hit).toBeNull();
    w = advanceWorld(w, 0, 'runner', 3, 'gentle', 'normal', false, 'left');
    w = advanceWorld(w, 0, 'runner', 3, 'gentle', 'normal', false, 'act');
    w = ticks(w, 4, 'runner');
    expect(w.hit).toBe(0);
    expect(w.misses).toBe(0);
    expect(advanceWorld(w, 0.05, 'runner', 3, 'gentle', 'normal', false, 'right')).toEqual(w);
  });
  it('runner obstacle without jump retries without emitting a learning answer', () => {
    let w = initialWorld();
    for (let i = 0; i < 500; i++)
      w = advanceWorld(w, 0.01, 'runner', 3, 'challenge', 'normal', false);
    expect(w.misses).toBeGreaterThan(0);
    expect(w.hit).toBeNull();
  });
  it('boat strokes change inertia, alternating strokes progress farther, and collision uses actual x', () => {
    const start = initialWorld();
    const left = advanceWorld(start, 0, 'boat', 3, 'gentle', 'normal', false, 'left');
    const same = advanceWorld(left, 0, 'boat', 3, 'gentle', 'normal', false, 'left');
    const alternating = advanceWorld(left, 0, 'boat', 3, 'gentle', 'normal', false, 'right');
    expect(left.vx).toBeLessThan(0);
    expect(alternating.distance).toBeGreaterThan(same.distance);
    let w = start;
    for (let i = 0; i < 11; i++)
      w = advanceWorld(w, 0, 'boat', 3, 'gentle', 'normal', false, 'act');
    expect(w.hit).toBe(1);
    const miss = advanceWorld(
      { ...start, x: 250, distance: 240 },
      0,
      'boat',
      3,
      'gentle',
      'normal',
      false,
      'act',
    );
    expect(miss.hit).toBeNull();
    expect(miss.misses).toBe(1);
  });
  it('drum holds a note in easy mode, passes it explicitly, and only hits within the window', () => {
    let w = ticks(initialWorld(), 3, 'drum');
    expect(w.distance).toBe(0);
    w = advanceWorld(w, 0, 'drum', 3, 'gentle', 'normal', false, 'pass');
    w = ticks(w, 4, 'drum');
    expect(targetPosition('drum', 1, 3, w, 'gentle').x).toBe(180);
    expect(advanceWorld(w, 0, 'drum', 3, 'gentle', 'normal', false, 'act').hit).toBe(1);
    const miss = advanceWorld(
      { ...initialWorld(), distance: 100 },
      0,
      'drum',
      3,
      'steady',
      'normal',
      false,
      'act',
    );
    expect(miss.hit).toBeNull();
    expect(miss.misses).toBe(1);
  });
  it('space launch flies before colliding; an empty launch never emits an option', () => {
    let w = advanceWorld(initialWorld(), 0, 'space', 3, 'gentle', 'normal', false, 'act');
    expect(w.hit).toBeNull();
    expect(w.shot?.y).toBe(350);
    w = ticks(w, 2, 'space');
    expect(w.hit).toBe(1);
    let miss = advanceWorld(
      { ...initialWorld(), x: 250 },
      0,
      'space',
      3,
      'gentle',
      'normal',
      false,
      'act',
    );
    miss = ticks(miss, 2, 'space');
    expect(miss.hit).toBeNull();
    expect(miss.misses).toBe(1);
  });
  it('speed affects movement, assist slows it, and dt rejects long inactive gaps', () => {
    const slow = ticks({ ...initialWorld(), distance: -200 }, 1, 'drum', false, 'slow');
    const fast = ticks({ ...initialWorld(), distance: -200 }, 1, 'drum', false, 'fast');
    expect(fast.distance).toBeGreaterThan(slow.distance);
    const assisted = ticks({ ...initialWorld(), distance: -200 }, 1, 'drum', true, 'fast');
    expect(assisted.distance).toBeLessThan(fast.distance);
    expect(
      advanceWorld(initialWorld(), 100, 'runner', 3, 'steady', 'fast', false).distance,
    ).toBeLessThan(10);
    expect(laneX(3, 4)).toBe(680);
  });
});

it('all four target positions are reachable and challenge narrows the rhythm window', () => {
  for (let index = 0; index < 4; index++) {
    let ship = { ...initialWorld(), x: laneX(index, 4) };
    ship = advanceWorld(ship, 0, 'space', 4, 'gentle', 'normal', false, 'act');
    for (let i = 0; i < 200; i++)
      ship = advanceWorld(ship, 0.01, 'space', 4, 'gentle', 'normal', false);
    expect(ship.hit).toBe(index);
    let runner = { ...initialWorld(), x: laneX(index, 4), distance: 145 };
    runner = advanceWorld(runner, 0, 'runner', 4, 'gentle', 'normal', false, 'act');
    for (let i = 0; i < 250; i++)
      runner = advanceWorld(runner, 0.01, 'runner', 4, 'gentle', 'normal', false);
    expect(runner.hit).toBe(index);
  }
  const edge = { ...initialWorld(), distance: 36 };
  expect(advanceWorld(edge, 0, 'drum', 3, 'gentle', 'normal', false, 'act').hit).toBe(0);
  expect(advanceWorld(edge, 0, 'drum', 3, 'challenge', 'normal', false, 'act').hit).toBeNull();
  const still = targetPosition('space', 0, 3, { ...initialWorld(), time: 2 }, 'gentle');
  const moving = targetPosition('space', 0, 3, { ...initialWorld(), time: 2 }, 'challenge');
  expect(Math.abs(still.x - moving.x)).toBeGreaterThan(40);
});
