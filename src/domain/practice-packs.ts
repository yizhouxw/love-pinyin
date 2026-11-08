import type { LearningAudio } from '../app/learning-voice';
import type { DailyReading } from './daily-reading';
import type { WordPracticeContent } from './word-practice';

export type PracticeSource = 'original' | 'household';

type PracticePack = {
  daily: DailyReading;
  words: WordPracticeContent;
  audioPrefix: string;
  lessons: LearningAudio['lessons'];
};

export type StandardAudioSource = {
  attribution: string;
  license: string;
  licenseUrl: string;
  url: string;
};

export type PracticePacks = {
  selected?: PracticeSource;
  original: PracticePack;
  household?: PracticePack;
  standardSources: StandardAudioSource[];
};
