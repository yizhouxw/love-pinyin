import hanziContent from '../../content/daily-reading-hanzi.json';
import playback from '../../content/playback.json';

export type DailyItem = {
  id: string;
  display: string;
  original: string;
  syllables: string[];
  audioIds: string[];
  audioNotes: string[];
  missingSyllables: string[];
  narrationId: string | null;
  spokenText: string | null;
  derivedAudio?: boolean;
  available: boolean;
  timings?: AudioTiming[];
  sentenceReading?: {
    narrationId: string;
    spokenText: string;
    available: boolean;
    timings: AudioTiming[];
  };
  wordExample?: { id: string; spokenText: string; examples: { text: string; pinyin: string }[] };
};
export type DailySection = {
  id: string;
  kind: 'phonics' | 'comparison' | 'spelling' | 'words' | 'sentences';
  title: string;
  instruction: string;
  items: DailyItem[];
};
export type DailyDay = {
  id: string;
  number: number;
  title: string;
  sourcePage: number;
  sections: DailySection[];
};
export type DailyReading = {
  ui: Record<string, string>;
  version: number;
  source: { filename: string; sha256: string; pages: number; practiceCount: number };
  days: DailyDay[];
  assessment: { available: boolean; mode: 'asr-syllable-match'; toneAssessed: false };
};
export type ReadingMark = 'practiced' | 'fluent' | 'again';

/** Hearing a demonstration or recording a voice never implies correct pronunciation. */
export function sectionSummary(section: DailySection, marks: Record<string, ReadingMark>) {
  return {
    total: section.items.length,
    practiced: section.items.filter((item) => marks[item.id]).length,
    parentFluent: section.items.filter((item) => marks[item.id] === 'fluent').length,
    parentAgain: section.items.filter((item) => marks[item.id] === 'again').length,
  };
}

export type AudioTiming = { start: number; end: number };

/** Leave time to repeat the item just heard, independent of its audio source. */
export function readingGapSeconds(item: Pick<DailyItem, 'syllables'>, baseSeconds: number): number {
  const extra = Math.max(0, item.syllables.length - 1) * playback.reading.extraSecondsPerSyllable;
  return Math.round((baseSeconds + extra) * 10) / 10;
}

/** Silence between spoken units clears the highlight; never estimates equal durations. */
export function highlightedSyllable(timings: AudioTiming[], seconds: number): number {
  return timings.findIndex((timing) => seconds >= timing.start && seconds < timing.end);
}

/** Each character travels with its syllable when a long sentence wraps. */
export function readingCharacters(id: string): string[] {
  const text = (hanziContent as Record<string, string>)[id];
  return text?.match(/\p{Script=Han}[^\p{Script=Han}]*/gu) ?? [];
}

export function readingHanzi(id: string): string | undefined {
  return (hanziContent as Record<string, string>)[id];
}
