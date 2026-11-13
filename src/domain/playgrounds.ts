import data from '../../content/game-playgrounds.json';
export type Playground = 'runner' | 'boat' | 'drum' | 'space';
export type Point = { x: number; y: number };
export type PlaygroundConfig = {
  scene: Playground;
  count: number;
  speed: number;
  assist: boolean;
  difficulty?: 'gentle' | 'steady' | 'challenge';
};
export type PlaygroundState = {
  x: number;
  y: number;
  vy: number;
  distance: number;
  time: number;
  hit: number | null;
  misses: number;
  collected: number[];
  flash: number;
  destination: Point | null;
  route: Point[];
  chosen: number | null;
  jumping: boolean;
  shot: { x: number; y: number; vx: number; vy: number } | null;
};
export const playgrounds = data;
export const clamp = (n: number, a: number, b: number) => Math.max(a, Math.min(b, n));
export const separation = (a: Point, b: Point) => Math.hypot(a.x - b.x, a.y - b.y);
export function startPlayground(): PlaygroundState {
  return {
    x: 240,
    y: 350,
    vy: 0,
    distance: 0,
    time: 0,
    hit: null,
    misses: 0,
    collected: [],
    flash: 0,
    destination: null,
    route: [],
    chosen: null,
    jumping: false,
    shot: null,
  };
}
export function dock(index: number, count: number): Point {
  return { x: 60 + (index * 360) / Math.max(1, count - 1), y: 78 };
}
export function planet(index: number, count: number): Point {
  return { ...dock(index, count), y: 80 + (index % 2) * 38 };
}
export function tree(state: PlaygroundState, count: number) {
  const step = data.runner.treeSpacing;
  const ordinal = Math.max(0, Math.floor((state.distance - data.runner.firstTree + 170) / step));
  return {
    index: ordinal % count,
    x: data.runner.firstTree + ordinal * step - state.distance,
    ordinal,
  };
}
export function jump(state: PlaygroundState): PlaygroundState {
  return state.y >= data.runner.ground
    ? { ...state, y: data.runner.ground, vy: -data.runner.jump, jumping: true }
    : state;
}
export function sail(state: PlaygroundState, point: Point): PlaygroundState {
  return {
    ...state,
    destination: { x: clamp(point.x, 25, 455), y: clamp(point.y, 55, 365) },
    route: [],
    chosen: null,
  };
}
/** Shortest safe route through a small visibility graph around circular reefs. */
export function boatRoute(from: Point, target: Point): Point[] {
  const reefs = data.boat.rocks;
  const nodes: Point[] = [
    from,
    target,
    ...reefs.flatMap((reef) =>
      Array.from({ length: 12 }, (_, i) => ({
        x: reef.x + Math.cos((i * Math.PI) / 6) * (reef.radius + 25),
        y: reef.y + Math.sin((i * Math.PI) / 6) * (reef.radius + 25),
      })),
    ),
  ];
  const clear = (a: Point, b: Point) =>
    reefs.every((reef) => {
      const dx = b.x - a.x,
        dy = b.y - a.y;
      const t = clamp(((reef.x - a.x) * dx + (reef.y - a.y) * dy) / (dx * dx + dy * dy || 1), 0, 1);
      return (
        separation(reef, { x: a.x + t * dx, y: a.y + t * dy }) >= reef.radius + data.boat.hullRadius
      );
    });
  const distance = nodes.map(() => Infinity),
    previous = nodes.map(() => -1),
    visited = new Set<number>();
  distance[0] = 0;
  for (let step = 0; step < nodes.length; step++) {
    let at = -1;
    for (let i = 0; i < nodes.length; i++)
      if (!visited.has(i) && (at < 0 || distance[i]! < distance[at]!)) at = i;
    if (at < 0 || !Number.isFinite(distance[at])) break;
    if (at === 1) break;
    visited.add(at);
    for (let i = 1; i < nodes.length; i++) {
      if (visited.has(i) || !clear(nodes[at]!, nodes[i]!)) continue;
      const cost = distance[at]! + separation(nodes[at]!, nodes[i]!);
      if (cost < distance[i]!) {
        distance[i] = cost;
        previous[i] = at;
      }
    }
  }
  if (previous[1] === -1) return [];
  const result: Point[] = [];
  for (let at = 1; at !== 0; at = previous[at]!) result.unshift(nodes[at]!);
  return result;
}
export function sailToDock(state: PlaygroundState, index: number, count: number): PlaygroundState {
  const route = boatRoute(state, dock(index, count));
  return { ...state, destination: route[0] ?? null, route: route.slice(1), chosen: index };
}
export function throwParcel(
  state: PlaygroundState,
  velocity: Point,
  chosen: number | null = null,
): PlaygroundState {
  if (state.shot) return state;
  return {
    ...state,
    chosen,
    shot: { x: 240, y: 350, vx: clamp(velocity.x, -400, 400), vy: clamp(velocity.y, -510, -80) },
  };
}
export function deliveryVelocity(index: number, count: number): Point {
  const goal = planet(index, count),
    t = 1.5;
  return { x: (goal.x - 240) / t, y: (goal.y - 350 - 0.5 * data.space.gravity * t * t) / t };
}
export function trajectory(velocity: Point): Point[] {
  return Array.from({ length: 25 }, (_, i) => {
    const t = i / 16;
    return { x: 240 + velocity.x * t, y: 350 + velocity.y * t + 0.5 * data.space.gravity * t * t };
  });
}
export function stepPlayground(
  prior: PlaygroundState,
  elapsed: number,
  c: PlaygroundConfig,
): PlaygroundState {
  const dt = clamp(elapsed, 0, 0.04);
  if (prior.hit !== null) return prior;
  const s = { ...prior, time: prior.time + dt, flash: Math.max(0, prior.flash - dt) };
  if (c.scene === 'runner') {
    const nextTree = tree(s, c.count);
    const approach = c.assist && s.y >= data.runner.ground && nextTree.x < 220 && nextTree.x > 60;
    s.distance += data.runner.speed * c.speed * dt * (approach ? data.runner.assistSpeedFactor : 1);
    s.vy += data.runner.gravity * dt;
    s.y = Math.min(data.runner.ground, s.y + s.vy * dt);
    if (s.y >= data.runner.ground) {
      s.vy = 0;
      s.jumping = false;
    }
    const fruit = tree(s, c.count);
    if (s.jumping && Math.abs(fruit.x - 110) < 32 && s.y < 280) s.hit = fruit.index;
    const logX = fruit.x - 120;
    if (Math.abs(logX - 110) < 22 && s.y > 306 && s.flash === 0) {
      s.misses++;
      s.flash = 0.8;
      s.vy = -220;
      s.jumping = false;
    }
  }
  if (c.scene === 'boat' && s.destination) {
    const delta = { x: s.destination.x - s.x, y: s.destination.y - s.y },
      distance = Math.hypot(delta.x, delta.y);
    const step = Math.min(distance, data.boat.speed * c.speed * dt);
    const next = {
      x: s.x + (distance ? (delta.x / distance) * step : 0),
      y: s.y + (distance ? (delta.y / distance) * step : 0),
    };
    if (data.boat.rocks.some((r) => separation(next, r) < r.radius + data.boat.hullRadius)) {
      s.destination = null;
      s.route = [];
      s.misses++;
      s.flash = 0.7;
    } else {
      s.x = next.x;
      s.y = next.y;
      if (distance < 4) {
        s.destination = s.route[0] ?? null;
        s.route = s.route.slice(1);
      }
    }
    data.boat.ducklings.forEach((duck, i) => {
      if (!s.collected.includes(i) && separation(s, duck) < 30) s.collected = [...s.collected, i];
    });
    for (let i = 0; i < c.count; i++)
      if (
        (s.chosen === i ||
          (s.chosen === null && separation(prior.destination!, dock(i, c.count)) < 28)) &&
        separation(s, dock(i, c.count)) < 28
      )
        s.hit = i;
  }
  if (c.scene === 'space' && s.shot) {
    const dtFlight = dt * c.speed;
    const radius = c.difficulty === 'challenge' ? 25 : c.difficulty === 'steady' ? 29 : 34;
    const p = { ...s.shot };
    p.x += p.vx * dtFlight;
    p.y += p.vy * dtFlight + 0.5 * data.space.gravity * dtFlight * dtFlight;
    p.vy += data.space.gravity * dtFlight;
    s.shot = p;
    for (let i = 0; i < c.count; i++)
      if ((s.chosen === null || s.chosen === i) && separation(p, planet(i, c.count)) < radius)
        s.hit = i;
    if (
      p.y > 405 ||
      p.x < 0 ||
      p.x > 480 ||
      data.space.rocks.some((r) => separation(p, r) < r.radius + 7)
    ) {
      s.shot = null;
      s.misses++;
      s.flash = 0.7;
    }
  }
  return s;
}
