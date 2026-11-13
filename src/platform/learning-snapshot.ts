import type { Answer, Bootstrap, Curriculum, Progress, Session } from '../domain/learning-api';
import type { LearningAudio } from '../app/learning-voice';
import { api } from './api-client';
import { replayPendingAnswer } from './pending-answer';

const object = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value);
const string = (value: unknown): value is string => typeof value === 'string';
const bool = (value: unknown): value is boolean => typeof value === 'boolean';
const count = (value: unknown) =>
  typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;

function requireContract<T>(value: unknown, check: (value: Record<string, unknown>) => boolean): T {
  if (!object(value) || !check(value)) throw new Error('LEARNING_RESPONSE_INVALID');
  return value as T;
}

function exercise(value: unknown): boolean {
  return (
    object(value) &&
    string(value.id) &&
    string(value.type) &&
    string(value.prompt) &&
    Array.isArray(value.options) &&
    value.options.every(
      (option: unknown) => object(option) && string(option.id) && string(option.label),
    )
  );
}

export const parseSession = (value: unknown) =>
  requireContract<Session>(
    value,
    (data) =>
      string(data.id) &&
      object(data.results) &&
      Array.isArray(data.tasks) &&
      data.tasks.every(
        (task: unknown) => object(task) && string(task.instanceId) && exercise(task.exercise),
      ),
  );

export const parseAnswer = (value: unknown) =>
  requireContract<Omit<Answer, 'selectedOptionId'>>(
    value,
    (data) =>
      bool(data.correct) &&
      string(data.correctOptionId) &&
      object(data.mastery) &&
      string(data.mastery.status),
  );

const parseProgress = (value: unknown) =>
  requireContract<Progress>(
    value,
    (data) =>
      count(data.revision) &&
      string(data.selectedLessonId) &&
      count(data.completedSessions) &&
      object(data.settings) &&
      bool(data.settings.soundEnabled) &&
      Array.isArray(data.mastery) &&
      data.mastery.every(
        (item: unknown) =>
          object(item) && string(item.knowledgeId) && string(item.status) && bool(item.reviewDue),
      ),
  );

const parseCurriculum = (value: unknown) =>
  requireContract<Curriculum>(
    value,
    (data) =>
      Array.isArray(data.lessons) &&
      data.lessons.every(
        (lesson: unknown) =>
          object(lesson) &&
          string(lesson.id) &&
          string(lesson.title) &&
          Array.isArray(lesson.exerciseIds) &&
          Array.isArray(lesson.knowledgeIds),
      ) &&
      Array.isArray(data.exercises) &&
      data.exercises.every(exercise) &&
      Array.isArray(data.knowledgeItems) &&
      Array.isArray(data.audioRequirements),
  );

export async function learningAnswer(path: string, options: RequestInit) {
  return parseAnswer(await api(path, options));
}

export async function learningSession(path: string, options: RequestInit) {
  const value: unknown = await api(path, options);
  // HTTP start responses predate the current-session results field.
  return parseSession(object(value) && !('results' in value) ? { ...value, results: {} } : value);
}

export async function loadLearningSnapshot(signal?: AbortSignal) {
  const boot = requireContract<Bootstrap>(await api('/bootstrap', { signal }), (data) =>
    bool(data.paired),
  );
  if (!boot.paired) return { loaded: false as const, boot };

  async function currentProgress() {
    const [stats, current] = await Promise.all([
      api('/profiles/progress', { signal }).then(parseProgress),
      api('/sessions/current', { signal }).then((value) =>
        value == null ? null : parseSession(value),
      ),
    ]);
    return { stats, current };
  }

  const [course, learning, sounds] = await Promise.all([
    api('/curriculum', { signal }).then(parseCurriculum),
    currentProgress(),
    api('/learning-audio', { signal }).catch(() => null),
  ]);
  signal?.throwIfAborted();
  const replayed = await replayPendingAnswer(learning.current, signal).catch(() => false);
  return {
    loaded: true as const,
    boot,
    course,
    ...(replayed ? await currentProgress() : learning),
    sounds: sounds as LearningAudio | null,
  };
}
