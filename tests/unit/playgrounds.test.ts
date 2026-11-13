import { describe, expect, it } from 'vitest';
import {
  deliveryVelocity,
  dock,
  jump,
  sail,
  sailToDock,
  startPlayground,
  stepPlayground,
  throwParcel,
  type PlaygroundConfig,
  type PlaygroundState,
} from '../../src/domain/playgrounds';
function run(state: PlaygroundState, config: PlaygroundConfig, seconds = 12) {
  for (let t = 0; t < seconds; t += 1 / 60) state = stepPlayground(state, 1 / 60, config);
  return state;
}
const config: PlaygroundConfig = {
  scene: 'runner',
  count: 4,
  speed: 0.85,
  assist: true,
  still: false,
};
describe('new touch playground physics', () => {
  it('passes every fruit without forced answers, including passive obstacle bounces', () => {
    for (const speed of [0.85, 1.35, 3.024]) {
      const passed = run({ ...startPlayground(), y: 330 }, { ...config, speed }, 30);
      expect(passed.hit).toBeNull();
      expect(passed.distance).toBeGreaterThan(1600);
    }
  });
  it('recovers from a reef contact to every dock rather than stranding near its clearance', () => {
    const settings = { ...config, scene: 'boat' as const };
    const stuck = run(sail({ ...startPlayground(), x: 150, y: 350 }, { x: 150, y: 220 }), settings);
    expect(stuck.misses).toBe(1);
    for (let i = 0; i < 4; i++) {
      const recovered = run(sailToDock(stuck, i, 4), settings, 15);
      expect(recovered.hit).toBe(i);
      expect(recovered.misses).toBe(stuck.misses);
    }
  });
  it('sailing past another dock does not submit a choice', () => {
    const crossed = run(
      sail({ ...startPlayground(), x: 30, y: 78 }, { x: 450, y: 78 }),
      { ...config, scene: 'boat' },
      5,
    );
    expect(crossed.hit).toBeNull();
    expect(crossed.x).toBeGreaterThan(446);
  });
  it('tree shortcuts still require a jump collision across supported speeds', () => {
    for (const speed of [0.85, 1, 1.35, 2.16, 3.024])
      for (let i = 0; i < 4; i++) {
        const s = jump({ ...startPlayground(), y: 330, distance: 500 + i * 280 - 170 });
        expect(run(s, { ...config, speed }, 2).hit).toBe(i);
      }
  });
  it('boat collisions stop movement without selecting or inventing learning results', () => {
    const s = run(sail({ ...startPlayground(), x: 150, y: 350 }, { x: 150, y: 100 }), {
      ...config,
      scene: 'boat',
    });
    expect(s.misses).toBe(1);
    expect(s.hit).toBeNull();
    expect(s.y).toBeGreaterThan(260);
  });
  it('tap docking routes reach every dock without crossing reefs', () => {
    for (let i = 0; i < 4; i++) {
      const s = run(sailToDock(startPlayground(), i, 4), { ...config, scene: 'boat' }, 15);
      expect(s.hit).toBe(i);
      expect(s.misses).toBe(0);
      expect(Math.hypot(s.x - dock(i, 4).x, s.y - 78)).toBeLessThan(29);
    }
  });
  it('direct delivery computes a real ballistic flight to each planet', () => {
    for (let count = 2; count <= 4; count++)
      for (let i = 0; i < count; i++) {
        const s = run(
          throwParcel(startPlayground(), deliveryVelocity(i, count)),
          { ...config, count, scene: 'space' },
          3,
        );
        expect(s.hit).toBe(i);
        expect(s.misses).toBe(0);
      }
  });
  it('missed parcel returns, cancellation stops rowing, reduced motion freezes physics', () => {
    const miss = run(
      throwParcel(startPlayground(), { x: 400, y: -80 }),
      { ...config, scene: 'space' },
      5,
    );
    expect(miss.shot).toBeNull();
    expect(miss.hit).toBeNull();
    expect(miss.misses).toBe(1);
    const initial = startPlayground();
    expect(run(initial, { ...config, scene: 'boat' }).x).toBe(initial.x);
    expect(stepPlayground(initial, 30, { ...config, still: true })).toBe(initial);
  });
});
