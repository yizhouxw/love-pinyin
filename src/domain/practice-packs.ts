import type { DailyReading } from './daily-reading';
import type { WordPracticeContent } from './word-practice';

export type PracticeSource = 'original' | 'household';

type PracticePack = { daily: DailyReading; words: WordPracticeContent };

export type StandardAudioSource = {
  attribution: string;
  license: string;
  licenseUrl: string;
  url: string;
};

export type IOSPracticePacks = {
  original: PracticePack;
  household?: PracticePack;
  standardSources: StandardAudioSource[];
};
