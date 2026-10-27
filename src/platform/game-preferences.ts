import type { Level, Speed } from '../domain/scene-game';
import { gameCatalog } from '../domain/games';
import { isGuest } from './guest';
export type ScenePreference = {
  difficulty: Level | 'auto';
  speed: Speed | 'auto';
  taskCount: number;
};
const storage = () => (isGuest() ? sessionStorage : localStorage);
export function readScenePreference(id: string): ScenePreference {
  try {
    const value: unknown = JSON.parse(storage().getItem(`love-pinyin.scene.${id}`) ?? '{}');
    if (
      value &&
      typeof value === 'object' &&
      'difficulty' in value &&
      'speed' in value &&
      typeof value.difficulty === 'string' &&
      typeof value.speed === 'string' &&
      ['auto', ...Object.keys(gameCatalog.levels)].includes(value.difficulty) &&
      ['auto', ...Object.keys(gameCatalog.speeds)].includes(value.speed)
    )
      return {
        ...value,
        taskCount:
          'taskCount' in value &&
          typeof value.taskCount === 'number' &&
          Number.isInteger(value.taskCount) &&
          value.taskCount >= gameCatalog.play.minTasks &&
          value.taskCount <= gameCatalog.play.maxTasks
            ? value.taskCount
            : gameCatalog.play.defaultTasks,
      } as ScenePreference;
  } catch {
    /* Browser may refuse local persistence; the game remains usable. */
  }
  return { difficulty: 'auto', speed: 'auto', taskCount: gameCatalog.play.defaultTasks };
}
export function saveScenePreference(id: string, preference: ScenePreference) {
  try {
    storage().setItem(`love-pinyin.scene.${id}`, JSON.stringify(preference));
  } catch {
    /* Optional preference. */
  }
}

export type SceneDisplay = { enlarged: boolean; assist: boolean; autoContinue: boolean };
export function readSceneDisplay(id: string, reducedMotion: boolean): SceneDisplay {
  try {
    const value = JSON.parse(sessionStorage.getItem(`love-pinyin.scene-view.${id}`) ?? '{}');
    return {
      enlarged: value.enlarged === true,
      assist: typeof value.assist === 'boolean' ? value.assist : reducedMotion,
      autoContinue: value.autoContinue !== false,
    };
  } catch {
    return { enlarged: false, assist: reducedMotion, autoContinue: true };
  }
}
export function saveSceneDisplay(id: string, value: SceneDisplay) {
  try {
    sessionStorage.setItem(`love-pinyin.scene-view.${id}`, JSON.stringify(value));
  } catch {
    /* Optional view preference. */
  }
}
