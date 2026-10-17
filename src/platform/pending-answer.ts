import type { PendingAnswer, Session } from '../domain/learning-api';
import { api } from './api-client';
import { isGuest } from './guest';

export const idempotencyKey = () => crypto.randomUUID();

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

export async function replayPendingAnswer(session: Session | null): Promise<boolean> {
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
      body: JSON.stringify(pending),
    });
    clearPendingAnswer(task.instanceId);
    return true;
  }
  return false;
}
