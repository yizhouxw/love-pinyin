import { describe, expect, it } from 'vitest';
import {
  advanceWorld,
  initialWorld,
  laneX,
  targetPosition,
  type EngineConfig,
  type World,
} from '../../src/domain/scene-game';
import { levelCatalog } from '../../src/domain/game-levels';
function config(id: string): EngineConfig {
  return {
    pattern: levelCatalog.patterns[id]!,
    count: 4,
    travel: 100,
    assist: true,
    targetRadius: 42,
    speedFactor: 1,
    targetMotion: 0,
    currentScale: 0,
  };
}
function step(w: World, c: EngineConfig, seconds: number) {
  for (let i = 0; i < seconds * 100; i++) w = advanceWorld(w, 0.01, c);
  return w;
}
describe('data-driven physical routes', () => {
  it('shows every candidate at entry without producing a learning hit', () => {
    for (const pattern of Object.values(levelCatalog.patterns)) {
      const c = config(pattern.id);
      const w = initialWorld();
      for (let i = 0; i < c.count; i++) {
        const p = targetPosition(i, w, c);
        expect(p.x).toBeGreaterThan(45);
        expect(p.x).toBeLessThan(770);
        expect(p.y).toBeGreaterThan(30);
        expect(p.y).toBeLessThan(400);
      }
      expect(w.hit).toBeNull();
    }
  });
  it('changing route data moves obstacles and the target, without changing the engine', () => {
    const c = config('runner-route-01');
    let w = step(initialWorld(), c, 5);
    expect(w.distance).toBe(c.pattern.obstacles[0]!.at - 25);
    const later = {
      ...c,
      pattern: {
        ...c.pattern,
        obstacles: c.pattern.obstacles.map((o) => ({ ...o, at: o.at + 90 })),
      },
    };
    w = step(initialWorld(), later, 5);
    expect(w.distance).toBe(later.pattern.obstacles[0]!.at - 25);
    expect(targetPosition(0, w, later).y).not.toBe(targetPosition(0, initialWorld(), later).y);
  });
  it('runner completes several obstacles, and all four gate lanes are reachable', () => {
    for (const pattern of Object.values(levelCatalog.patterns).filter((p) => p.scene === 'runner'))
      for (let target = 0; target < 4; target++) {
        const c = { ...config(pattern.id), pattern };
        let w = initialWorld();
        for (let n = 0; n < 5000 && w.hit === null; n++) {
          const o = pattern.obstacles.find((o) => !w.cleared.includes(o.id) && o.at > w.distance);
          if (o && o.at - w.distance < 45) {
            if (
              o.kind === 'root' &&
              (o.lane === -1 || Math.abs(laneX(o.lane % 4, 4) - w.x) < 55) &&
              w.jump === 0
            )
              w = advanceWorld(w, 0, c, 'act');
            if (o.kind === 'bush' && Math.abs(laneX(o.lane % 4, 4) - w.x) < 70)
              w = advanceWorld(w, 0, c, w.x < 500 ? 'right' : 'left');
          } else if (!o && Math.abs(w.x - laneX(target, 4)) > 20)
            w = advanceWorld(w, 0, c, w.x < laneX(target, 4) ? 'right' : 'left');
          if (!o && w.distance >= pattern.choiceAt - 65 && Math.abs(w.x - laneX(target, 4)) < 20)
            w = advanceWorld(w, 0, c, 'act');
          w = advanceWorld(w, 0.02, c);
        }
        expect(w.hit, `${pattern.id} target ${target}`).toBe(target);
      }
  });
  it('boat strokes create actual forward inertia and reefs pause rather than grading an answer', () => {
    const c = config('boat-route-01');
    const w = advanceWorld(initialWorld(), 0, c, 'act');
    expect(w.distance).toBe(0);
    expect(w.forwardVelocity).toBeGreaterThan(0);
    expect(step(w, c, 0.5).distance).toBeGreaterThan(10);
    let blocked = { ...initialWorld(), x: laneX(0, 4), distance: c.pattern.obstacles[0]!.at - 30 };
    for (let n = 0; n < 100; n++) {
      blocked = advanceWorld(blocked, 0, c, 'act');
      blocked = advanceWorld(blocked, 0.05, c);
    }
    expect(blocked.hit).toBeNull();
    expect(blocked.distance).toBe(c.pattern.obstacles[0]!.at - 25);
  });
  it('drum charts include real warmup beats, then every labelled note remains reachable', () => {
    for (const p of Object.values(levelCatalog.patterns).filter((p) => p.scene === 'drum')) {
      const c = config(p.id);
      let w = { ...initialWorld(), distance: p.beats[0]! };
      w = advanceWorld(w, 0, c, 'act');
      expect(w.beatHits).toEqual([p.beats[0]]);
      expect(w.hit).toBeNull();
      for (let i = 0; i < 4; i++) {
        const note = { ...initialWorld(), distance: p.choiceAt + i * p.choiceGap, note: i };
        expect(advanceWorld(note, 0, c, 'act').hit).toBe(i);
      }
    }
  });
  it('space requires playing through the flight, shoots obstacles, and then reaches all planets', () => {
    for (const p of Object.values(levelCatalog.patterns).filter((p) => p.scene === 'space')) {
      const c = config(p.id),
        rock = p.obstacles[0]!;
      let w = { ...initialWorld(), x: laneX(rock.lane % 4, 4), distance: rock.at - 25 };
      w = advanceWorld(w, 0, c, 'act');
      w = step(w, c, 0.2);
      expect(w.cleared).toContain(rock.id);
      expect(w.hit).toBeNull();
      for (let i = 0; i < 4; i++) {
        w = { ...initialWorld(), distance: p.choiceAt, x: laneX(i, 4) };
        w = advanceWorld(w, 0, c, 'act');
        w = step(w, c, 2);
        expect(w.hit, `${p.id} planet ${i}`).toBe(i);
      }
    }
  });
  it('misses, motor collectibles and timing never manufacture learning hits', () => {
    const c = config('runner-route-01');
    let w = { ...initialWorld(), x: laneX(0, 4) };
    w = step(w, c, 0.8);
    expect(w.collected).toContain('p1');
    expect(w.hit).toBeNull();
    const drum = config('drum-route-01');
    expect(advanceWorld(initialWorld(), 0, drum, 'act').hit).toBeNull();
    const space = config('space-route-01');
    let shot = { ...initialWorld(), x: 210, distance: space.pattern.choiceAt };
    shot = advanceWorld(shot, 0, space, 'act');
    shot = step(shot, space, 2);
    expect(shot.hit).toBeNull();
    expect(shot.misses).toBeGreaterThan(0);
  });
  it('speed changes actual movement, long inactive frames are bounded and resolved hits are immutable', () => {
    const c = config('runner-route-01'),
      slow = { ...c, speedFactor: 0.5 },
      fast = { ...c, speedFactor: 1.3 };
    expect(step(initialWorld(), fast, 0.5).distance).toBeGreaterThan(
      step(initialWorld(), slow, 0.5).distance,
    );
    expect(advanceWorld(initialWorld(), 100, c).distance).toBeLessThan(10);
    const hit = { ...initialWorld(), hit: 2 };
    expect(advanceWorld(hit, 0.1, c, 'left')).toEqual(hit);
  });
});
