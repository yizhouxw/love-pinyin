import { expect, it } from 'vitest';

import content from '../../content/daily-reading.json';
import hanzi from '../../content/daily-reading-hanzi.json';
import { readingCharacters, readingHanzi, type DailyReading } from '../../src/domain/daily-reading';

it('pairs every word and sentence syllable with a character, preserving spoken text and punctuation', () => {
  const annotated = (content as unknown as DailyReading).days.flatMap((day) =>
    day.sections
      .filter((section) => /词语|句子/.test(section.title))
      .flatMap((section) => section.items),
  );
  expect(Object.keys(hanzi)).toHaveLength(annotated.length);
  for (const item of annotated) {
    expect(readingCharacters(item.id), item.id).toHaveLength(item.syllables.length);
    expect(readingCharacters(item.id).join('')).toBe(readingHanzi(item.id));
    if (item.spokenText) expect(readingHanzi(item.id)).toBe(item.spokenText);
  }
  expect(readingCharacters('day-06-s6-i1')[4]).toBe('画，');
  expect(readingCharacters('day-01-s1-i1')).toEqual([]);
});
