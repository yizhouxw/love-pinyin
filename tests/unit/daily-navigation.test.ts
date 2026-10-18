import { expect, it } from 'vitest';

import reading from '../../content/daily-reading.json';
import navigation from '../../content/daily-reading-navigation.json';

it('DAILY-07 groups every source item once in its original playback order', () => {
  const sections = reading.days.flatMap((day) => day.sections);
  expect(Object.keys(navigation)).toEqual(sections.map((section) => section.id));
  for (const section of sections) {
    const groups = navigation[section.id as keyof typeof navigation];
    expect(groups.flatMap((group) => group.itemIds)).toEqual(section.items.map((item) => item.id));
    for (const group of groups) {
      expect(group.itemIds.length).toBeGreaterThan(0);
      expect(group.itemIds.length).toBeLessThanOrEqual(8);
      if (group.compact) {
        expect(
          section.items
            .filter((item) => group.itemIds.includes(item.id))
            .every((item) => item.syllables.length === 1),
        ).toBe(true);
      }
    }
  }
  expect(navigation['day-01-section-1'][0]!.itemIds).toEqual([
    'day-01-s1-i1',
    'day-01-s1-i2',
    'day-01-s1-i3',
    'day-01-s1-i4',
    'day-01-s1-i5',
  ]);
});
