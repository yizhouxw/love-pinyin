import type { Level, Speed } from '../domain/scene-game';
import { gameCatalog } from '../domain/games';
import { isGuest } from './guest';
export type ScenePreference = { difficulty: Level | 'auto'; speed: Speed | 'auto' };
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
      return value as ScenePreference;
  } catch {
    /* Browser may refuse local persistence; the game remains usable. */
  }
  return { difficulty: 'auto', speed: 'auto' };
}
export function saveScenePreference(id: string, preference: ScenePreference) {
  try {
    storage().setItem(`love-pinyin.scene.${id}`, JSON.stringify(preference));
  } catch {
    /* Optional preference. */
  }
}
