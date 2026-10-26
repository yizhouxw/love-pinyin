/** Explicit developer-only assembly; never imported by the product UI. */
import { days } from '../../../content/daily-reading.json';
import type { PronunciationTarget } from '../../domain/pronunciation';
import { coursePronunciationTargets } from '../../domain/pronunciation-practice';

export const pronunciationTargets: readonly PronunciationTarget[] = [
  ...coursePronunciationTargets,
  ...days.flatMap((day) =>
    day.sections.flatMap((section) =>
      section.items.map((item) => ({
        id: item.id,
        pinyin: item.syllables.join(' '),
        task: item.syllables.length > 1 ? ('sequence' as const) : ('syllable' as const),
      })),
    ),
  ),
];
