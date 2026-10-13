import { describe, expect, it } from 'vitest';
import { sectionSummary, type DailySection } from '../src/domain/daily-reading';

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
