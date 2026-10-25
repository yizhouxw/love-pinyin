/** Learning API response projections shared by browser adapters and React views. */
import type { IllustrationCatalog } from './illustrations';
import type { WritingCatalog, WritingOption } from './writing';

/* eslint-disable @typescript-eslint/no-explicit-any -- API JSON mirrors the versioned content schema. */
export type Json = Record<string, any>;

export type Bootstrap = {
  paired: boolean;
  guest?: boolean;
  isLocalHost?: boolean;
  device?: { label: string; isParent: boolean };
  profile?: {
    roundsSinceBreak?: number;
    settings?: { reducedMotion?: boolean; soundEnabled?: boolean; playbackGapSeconds?: number };
    [key: string]: unknown;
  };
};

export type Option = { id: string; label: string; writing?: WritingOption; pictureId?: string };

export type Lesson = {
  id: string;
  order: number;
  title: string;
  objectives: string[];
  knowledgeIds: string[];
  exerciseIds: string[];
  suggestedSessionMinutes?: number;
};

export type Exercise = {
  id: string;
  type: string;
  prompt: string;
  options: Option[];
  audioRef?: string;
  pictureId?: string;
};

export type Knowledge = {
  id: string;
  lessonId: string;
  category: string;
  symbol: string;
  teachingNote: string;
};

export type Task = { instanceId: string; exercise: Exercise };

export type PendingAnswer = { requestId: string; answerOptionId: string };

export type Session = {
  id: string;
  gameId?: string | null;
  gameRun?: import('./game-levels').GameRun;
  gameSettings?: import('./scene-game').GameSettings;
  lessonId?: string;
  reviewKnowledgeId?: string | null;
  tasks: Task[];
  results: Record<string, unknown>;
};

export type Progress = {
  revision: number;
  selectedLessonId: string;
  completedSessions: number;
  clockSkewDetected?: boolean;
  pendingClockAttempts?: number;
  attemptCount?: number;
  settings: {
    reducedMotion: boolean;
    soundEnabled: boolean;
    playbackGapSeconds?: number;
    gameSessionMinutes?: number;
    gameDailyMinutes?: number;
  };
  mastery: {
    knowledgeId: string;
    status: string;
    reviewDue: boolean;
    reviewDueDate: string | null;
    sampleSize: number;
    correctCount: number;
    accuracy: number | null;
    coveredModes: string[];
    requiredModes: string[];
  }[];
  reviewRecommendations?: {
    knowledgeId: string;
    symbol: string;
    lessonId: string;
    lessonTitle: string;
    dueDate: string;
    overdueDays: number;
  }[];
};

export type AttemptRecord = {
  id: string;
  mode: string;
  firstTryCorrect: boolean;
  hintUsed: boolean;
  occurredAt: string;
  dueCredit: boolean;
  clockPending: boolean;
};

export type AttemptHistoryPage = {
  items: AttemptRecord[];
  nextCursor: string | null;
  loaded: boolean;
  loading: boolean;
  error: boolean;
};

export type Curriculum = {
  contentVersion?: string;
  illustrations?: IllustrationCatalog;
  writing?: WritingCatalog;
  lessons: Lesson[];
  knowledgeItems: Knowledge[];
  exercises: Exercise[];
  audioRequirements: AudioRequirement[];
  inventory?: { initials: string[] };
};

export type AudioRequirement = {
  id: string;
  available?: boolean;
  knowledgeIds: string[];
  standardSource?: { title: string; exampleTone: number | null } | null;
};

export type Answer = {
  correct: boolean;
  correctOptionId: string;
  selectedOptionId: string;
  mastery: { status: string };
  clockPending?: boolean;
  explanation?: string;
  explanationAudioId?: string;
};

export type Hint = { explanation: string; answer: { optionId: string } };

export type Narration = {
  ui: Record<string, { text: string }>;
  exercises: Record<string, { text: string; visualCue?: string; options: Record<string, string> }>;
};
