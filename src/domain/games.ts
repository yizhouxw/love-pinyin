import catalog from '../../content/games.json';
export const gameCatalog = catalog;
export type GameClock = {
  day: string;
  dailySeconds: number;
  sessionSeconds: number;
  remainingSeconds: number;
  reason: string | null;
  breakRemainingSeconds: number;
  leaseSeconds: number;
  sessionMinutes: number;
  dailyMinutes: number;
};
export type GameReport = {
  answered: number;
  independentCorrect: number;
  hints: number;
  skipped: number;
  pendingClock: number;
  practiceKnowledgeIds: string[];
};
export type GameOverview = {
  clock: GameClock;
  report: GameReport;
  recommendation?: import('./scene-game').GameSettings['recommendation'];
};
