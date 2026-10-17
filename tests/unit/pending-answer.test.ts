import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import type { Session } from '../../src/domain/learning-api';
import { api } from '../../src/platform/api-client';
import { isGuest } from '../../src/platform/guest';
import {
  clearPendingAnswer,
  readPendingAnswer,
  replayPendingAnswer,
  savePendingAnswer,
} from '../../src/platform/pending-answer';

vi.mock('../../src/platform/api-client', () => ({ api: vi.fn() }));
vi.mock('../../src/platform/guest', () => ({ isGuest: vi.fn() }));
let cache: Map<string, string>;
const pending = { requestId: 'original-request', answerOptionId: 'b' };
const session: Session = {
  id: 'session',
  results: {},
  tasks: ['one', 'two'].map((instanceId) => ({
    instanceId,
    exercise: { id: 'exercise', type: 'symbol-choice', prompt: '', options: [] },
  })),
};
beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(isGuest).mockReturnValue(false);
  cache = new Map();
  vi.stubGlobal('sessionStorage', {
    getItem: (key: string) => cache.get(key) ?? null,
    setItem: (key: string, value: string) => cache.set(key, value),
    removeItem: (key: string) => cache.delete(key),
  });
});
afterEach(() => vi.unstubAllGlobals());

describe('pending answer recovery', () => {
  it('isolates guest and household pending requests in the same tab', () => {
    savePendingAnswer('one', pending);
    vi.mocked(isGuest).mockReturnValue(true);
    expect(readPendingAnswer('one')).toBeNull();
    savePendingAnswer('one', { ...pending, requestId: 'guest-request' });
    clearPendingAnswer('one');
    vi.mocked(isGuest).mockReturnValue(false);
    expect(readPendingAnswer('one')).toEqual(pending);
  });

  it.each(['{broken', '{}', '{"requestId":42,"answerOptionId":"a"}'])(
    'ignores damaged records: %s',
    (raw) => {
      cache.set('lp.pending-answer.one', raw);
      expect(readPendingAnswer('one')).toBeNull();
    },
  );

  it('tolerates disabled browser storage', () => {
    vi.stubGlobal('sessionStorage', {
      getItem: () => {
        throw new Error('blocked');
      },
      setItem: () => {
        throw new Error('blocked');
      },
      removeItem: () => {
        throw new Error('blocked');
      },
    });
    expect(readPendingAnswer('one')).toBeNull();
    expect(() => savePendingAnswer('one', pending)).not.toThrow();
    expect(() => clearPendingAnswer('one')).not.toThrow();
  });

  it('replays only one unconfirmed answer with its original idempotency key', async () => {
    savePendingAnswer('one', pending);
    savePendingAnswer('two', { ...pending, requestId: 'second-request' });
    expect(await replayPendingAnswer(session)).toBe(true);
    expect(api).toHaveBeenCalledExactlyOnceWith('/instances/one/answer', {
      method: 'POST',
      body: JSON.stringify(pending),
    });
    expect(readPendingAnswer('one')).toBeNull();
    expect(readPendingAnswer('two')?.requestId).toBe('second-request');
  });

  it('clears already acknowledged answers without resubmitting them', async () => {
    savePendingAnswer('one', pending);
    expect(await replayPendingAnswer({ ...session, results: { one: { correct: true } } })).toBe(
      false,
    );
    expect(api).not.toHaveBeenCalled();
    expect(readPendingAnswer('one')).toBeNull();
    expect(await replayPendingAnswer(null)).toBe(false);
  });

  it('retains the original request when replay fails so the next reconnect can retry', async () => {
    savePendingAnswer('one', pending);
    vi.mocked(api).mockRejectedValue(new Error('MAC_UNREACHABLE'));
    await expect(replayPendingAnswer(session)).rejects.toThrow('MAC_UNREACHABLE');
    expect(readPendingAnswer('one')).toEqual(pending);
  });
});
