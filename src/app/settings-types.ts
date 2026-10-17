import type { Curriculum, Progress } from '../domain/learning-api';

/** Shared page inputs; all persistence stays with the application coordinator. */
export type LearningSettingsProps = {
  curriculum: Curriculum;
  progress: Progress;
  lessonChoice: string;
  setLessonChoice: (id: string) => void;
  busy: boolean;
  refresh: () => Promise<void>;
  act: (work: () => Promise<void>) => Promise<void>;
};
