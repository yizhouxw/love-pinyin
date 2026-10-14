/** Contract baseline; API implementations belong to the numbered SPECs. */
export type KnowledgeId = string;
export type LessonId = string;
export type ExerciseMode = 'listen-choice' | 'symbol-choice' | 'tone-choice' | 'blend-choice';

export interface Attempt {
  id: string;
  sessionId: string;
  exerciseId: string;
  knowledgeId: KnowledgeId;
  mode: ExerciseMode;
  firstTryCorrect: boolean;
  hintUsed: boolean;
  occurredAt: string;
  receivedAt: string;
  contentVersion: string;
  /** True while awaiting a parent decision after the Mac clock moved backwards. */
  clockPending?: boolean;
}

export interface ProgressSnapshot {
  schemaVersion: 1;
  contentVersion: string;
  profileId: string;
  revision: number;
  selectedLessonId: LessonId;
  /** Server-derived count of fully completed sessions; drives the non-competitive garden. */
  completedSessions: number;
  clockSkewDetected: boolean;
  pendingClockAttempts: number;
  attempts: Attempt[];
  settings: {
    soundEnabled: boolean;
    reducedMotion: boolean;
    sessionMinutes: number;
    playbackGapSeconds?: number;
  };
}

export interface AudioPlayer {
  play(audioId: string, signal?: AbortSignal): Promise<void>;
  stop(): void;
}

export interface ProgressRepository {
  load(profileId: string): Promise<ProgressSnapshot>;
  appendAttempt(attempt: Attempt, expectedRevision: number): Promise<ProgressSnapshot>;
}
