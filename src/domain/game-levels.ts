/** Authored routes are a separate content layer, with no teaching answers. */
import data from '../../content/game-levels.json';
import type { Scene, Level } from './scene-game';
export type Obstacle = {
  id: string;
  at: number;
  lane: number;
  kind: 'root' | 'bush' | 'reef' | 'asteroid';
  size: number;
};
export type RoutePattern = {
  id: string;
  scene: Scene;
  length: number;
  choiceAt: number;
  choiceGap: number;
  currentStrength: number;
  travelScale: number;
  obstacles: Obstacle[];
  pickups: { id: string; at: number; lane: number }[];
  beats: number[];
};
export type RouteTheme = { id: string; sky: string; horizon: string; land: string; accent: string };
export type RouteLevel = {
  id: string;
  gameId: string;
  scene: Scene;
  number: number;
  title: string;
  subtitle: string;
  voiceId: string;
  recommendedDifficulty: Level;
  themeId: string;
  chapters: { id: string; title: string; segments: { id: string; patternId: string }[] }[];
};
export type GameRun = {
  version: 1;
  catalogVersion: 1;
  level: RouteLevel;
  theme: RouteTheme;
  patterns: Record<string, RoutePattern>;
  bindings: { segmentId: string; instanceId: string }[];
};
export const levelCatalog = data as {
  version: 1;
  themes: Record<string, RouteTheme>;
  patterns: Record<string, RoutePattern>;
  levels: RouteLevel[];
};
export function segmentAt(run: GameRun, index: number) {
  const all = run.level.chapters.flatMap((chapter, chapterIndex) =>
    chapter.segments.map((segment) => ({ ...segment, chapter, chapterIndex })),
  );
  return all[index];
}
/** Only for old six-task sessions; new sessions always carry a frozen server run. */
export function compatibleRun(gameId: string, instances: string[]): GameRun {
  const level = levelCatalog.levels.find((l) => l.gameId === gameId)!;
  const all = level.chapters.flatMap((c) => c.segments);
  return {
    version: 1,
    catalogVersion: 1,
    level,
    theme: levelCatalog.themes[level.themeId]!,
    patterns: levelCatalog.patterns,
    bindings: instances.map((instanceId, i) => ({ instanceId, segmentId: all[i]!.id })),
  };
}
