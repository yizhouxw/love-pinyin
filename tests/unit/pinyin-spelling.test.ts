import { expect, it } from 'vitest';
import { isWholeSyllable, pinyinSyllables, spellingPlan } from '../../src/domain/pinyin-spelling';

it('spells regular syllables and plays whole-recognition syllables intact with their tone', () => {
  const plan = spellingPlan(pinyinSyllables('bái shí YǓ guā jù'), [
    'bai2',
    'shi2',
    'yu3',
    'gua1',
    'ju4',
  ]);
  expect(plan.map(({ id, position }) => [id, position])).toEqual([
    ['audio-initial-b', 0],
    ['audio-final-ai', 0],
    ['spelling-bai2', 0],
    ['spelling-shi2', 1],
    ['spelling-yu3', 2],
    ['audio-initial-g', 3],
    ['audio-final-u', 3],
    ['audio-final-a', 3],
    ['spelling-gua1', 3],
    ['audio-initial-j', 4],
    ['audio-final-v', 4],
    ['spelling-ju4', 4],
  ]);
  expect(isWholeSyllable('shī')).toBe(true);
  expect(isWholeSyllable('shǒu')).toBe(false);
});

it('reuses the practice sound when available and avoids a wrong-tone clip for neutral syllables', () => {
  expect(spellingPlan(['yǐ'], ['yi3'], ['daily-yi3'])).toEqual([
    { kind: 'daily-audio', id: 'daily-yi3', position: 0 },
  ]);
  expect(spellingPlan(['zi'], ['zi1', 'zi4'])).toEqual([]);
});
