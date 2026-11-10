import { expect, it } from 'vitest';
import { isWholeSyllable, pinyinSyllables, spellingPlan } from '../../src/domain/pinyin-spelling';

it('spells regular syllables and plays whole-recognition syllables intact with their tone', () => {
  const plan = spellingPlan(pinyinSyllables('bái shí YǓ guā jù'), [
    'bai2',
    'shi2',
    'yu3',
    'gua1',
    'ju4',
    'final-ai2',
    'final-a1',
    'final-v4',
  ]);
  expect(plan.map(({ id, position }) => [id, position])).toEqual([
    ['audio-initial-b', 0],
    ['spelling-final-ai2', 0],
    ['spelling-bai2', 0],
    ['spelling-shi2', 1],
    ['spelling-yu3', 2],
    ['audio-initial-g', 3],
    ['audio-final-u', 3],
    ['spelling-final-a1', 3],
    ['spelling-gua1', 3],
    ['audio-initial-j', 4],
    ['spelling-final-v4', 4],
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
  expect(spellingPlan(['ba'], ['final-a1', 'final-a4'], ['daily-ba'])).toEqual([
    { kind: 'daily-audio', id: 'daily-ba', position: 0 },
  ]);
  expect(spellingPlan(['ba'], ['final-a1'], ['daily-ba1']).map(({ id }) => id)).toEqual([
    'audio-initial-b',
    'spelling-final-a1',
    'daily-ba1',
  ]);
});

it('carries the target tone on the final of a three-part syllable and on a nasal final', () => {
  expect(
    spellingPlan(
      ['guǎ', 'hóng', 'wǎn'],
      ['gua3', 'hong2', 'wan3', 'final-a3', 'final-ong2', 'final-an3'],
    ).map(({ id }) => id),
  ).toEqual([
    'audio-initial-g',
    'audio-final-u',
    'spelling-final-a3',
    'spelling-gua3',
    'audio-initial-h',
    'spelling-final-ong2',
    'spelling-hong2',
    'audio-final-u',
    'spelling-final-an3',
    'spelling-wan3',
  ]);
});

it('falls back to the complete syllable when a pack lacks the matching final', () => {
  expect(spellingPlan(['bà'], ['ba4', 'final-a1'])).toEqual([
    { kind: 'daily-audio', id: 'spelling-ba4', position: 0 },
  ]);
});
