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
  available: boolean;
  timings?: AudioTiming[];
  wordExample?: { id: string; spokenText: string; examples: { text: string; pinyin: string }[] };
};
export type DailySection = {
  id: string;
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

/** Silence between spoken units clears the highlight; never estimates equal durations. */
export function highlightedSyllable(timings: AudioTiming[], seconds: number): number {
  return timings.findIndex((timing) => seconds >= timing.start && seconds < timing.end);
}
