import type { PendingAnswer, Session } from '../domain/learning-api';
import { api } from './api-client';
import { isGuest } from './guest';

export const idempotencyKey = () =>
  typeof crypto.randomUUID === 'function'
    ? crypto.randomUUID()
    : Array.from(crypto.getRandomValues(new Uint8Array(16)), (value) =>
        value.toString(16).padStart(2, '0'),
      ).join('');

const pendingAnswerKey = (instanceId: string) =>
  `lp.${isGuest() ? 'guest.' : ''}pending-answer.${instanceId}`;

export function readPendingAnswer(instanceId: string): PendingAnswer | null {
  try {
    const raw = sessionStorage.getItem(pendingAnswerKey(instanceId));
    if (!raw) return null;
    const value = JSON.parse(raw) as Partial<PendingAnswer>;
    return typeof value.requestId === 'string' && typeof value.answerOptionId === 'string'
      ? { requestId: value.requestId, answerOptionId: value.answerOptionId }
      : null;
  } catch {
    return null;
  }
}

export function savePendingAnswer(instanceId: string, answer: PendingAnswer) {
  try {
    sessionStorage.setItem(pendingAnswerKey(instanceId), JSON.stringify(answer));
  } catch {
    // Server-side session recovery still prevents scoring the same instance twice.
  }
}

export function clearPendingAnswer(instanceId: string) {
  try {
    sessionStorage.removeItem(pendingAnswerKey(instanceId));
  } catch {
    // Storage may be disabled by the browser; the server remains authoritative.
  }
}

export async function replayPendingAnswer(
  session: Session | null,
  signal?: AbortSignal,
): Promise<boolean> {
  if (!session) return false;
  for (const task of session.tasks) {
    const pending = readPendingAnswer(task.instanceId);
    if (!pending) continue;
    if (session.results?.[task.instanceId]) {
      clearPendingAnswer(task.instanceId);
      continue;
    }
    await api(`/instances/${task.instanceId}/answer`, {
      method: 'POST',
      signal,
      body: JSON.stringify(pending),
    });
    clearPendingAnswer(task.instanceId);
    return true;
  }
  return false;
}

export function clearPendingLearningAnswers() {
  try {
    for (const key of Object.keys(sessionStorage)) {
      if (key.startsWith('lp.pending-answer.')) sessionStorage.removeItem(key);
    }
  } catch {
    // This storage can be unavailable; the saved archive is authoritative.
  }
}
