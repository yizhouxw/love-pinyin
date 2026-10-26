/** Explicit developer-only assembly; never imported by the product UI. */
import { days } from '../../../content/daily-reading.json';
import { inventory } from '../../../content/curriculum.json';
import practice from '../../../content/pronunciation-practice.json';
import type { PronunciationTarget } from '../../domain/pronunciation';
import { coursePronunciationTargets } from '../../domain/pronunciation-practice';

const initials = new Set([...inventory.initials, ...inventory.orthographicLetters]);

export const pronunciationTargets: readonly PronunciationTarget[] = [
  ...coursePronunciationTargets,
  ...days.flatMap((day) =>
    day.sections.flatMap((section) =>
      section.items.map((item) => ({
        id: item.id,
        pinyin: item.syllables.join(' '),
        task: (practice.dailySectionTasks[
          section.kind as keyof typeof practice.dailySectionTasks
        ] ??
          (item.syllables.length > 1
            ? 'sequence'
            : initials.has(item.syllables[0]!)
              ? 'initial'
              : 'syllable')) as PronunciationTarget['task'],
      })),
    ),
  ),
];
