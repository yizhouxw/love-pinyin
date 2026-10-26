import practice from '../../content/pronunciation-practice.json';
import { readingTargets } from '../../content/curriculum.json';
import type {
  PronunciationMatchResult,
  PronunciationRecognitionResult,
  PronunciationTarget,
} from './pronunciation';

export type PronunciationAssessment = {
  match: PronunciationMatchResult;
  recognition: PronunciationRecognitionResult;
  createdAt: string;
  saved: boolean;
};
export type PronunciationHistory = {
  items: PronunciationAssessment[];
  counts: Partial<Record<PronunciationMatchResult['status'], number>>;
};

export const coursePronunciationTargets = readingTargets.map((target) => ({
  id: target.id,
  pinyin: target.pinyin,
  task: practice.taskByPronunciationForm[
    target.pronunciationForm as keyof typeof practice.taskByPronunciationForm
  ] as PronunciationTarget['task'],
  lessonId: target.lessonId,
  audioId: target.audioRef,
}));
/** Refusals have no correctness value; mock results are never real learning evidence. */
export function pronunciationSummary(history: PronunciationHistory) {
  const matched = history.counts.matched ?? 0;
  const retry = history.counts.retry ?? 0;
  return {
    matched,
    assessed: matched + retry,
    undecided: (history.counts.uncertain ?? 0) + (history.counts.unavailable ?? 0),
  };
}
