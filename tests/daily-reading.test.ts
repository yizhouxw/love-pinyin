import { describe, expect, it } from 'vitest';
import { readingNavigation, sectionSummary, type DailySection } from '../src/domain/daily-reading';

describe('daily reading marks', () => {
  const section = { items: [{ id: 'one' }, { id: 'two' }, { id: 'three' }] } as DailySection;
  it('keeps self practice and parent observations separate from correctness', () => {
    expect(sectionSummary(section, {})).toEqual({
      total: 3,
      practiced: 0,
      parentFluent: 0,
      parentAgain: 0,
    });
    expect(
      sectionSummary(section, { one: 'practiced', two: 'fluent', three: 'again', other: 'fluent' }),
    ).toEqual({ total: 3, practiced: 3, parentFluent: 1, parentAgain: 1 });
  });
});

it('covers new material IDs and rejects partial or stale directory groups', () => {
  const section = {
    id: 'original-day-01-1',
    title: '听音跟读',
    kind: 'phonics',
    items: [{ id: 'new-one' }, { id: 'new-two' }],
  } as DailySection;
  expect(readingNavigation(section).flatMap((group) => group.itemIds)).toEqual([
    'new-one',
    'new-two',
  ]);
  expect(
    readingNavigation({ ...section, id: 'day-01-section-1' }).flatMap((group) => group.itemIds),
  ).toEqual(['new-one', 'new-two']);
});
