import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import {
  guestApi,
  isGuest,
  learningAssetUrl,
  startGuest,
  leaveGuest,
} from '../../src/platform/guest';

let cache: Map<string, string>;
beforeEach(() => {
  cache = new Map();
  vi.stubGlobal('sessionStorage', {
    getItem: (key: string) => cache.get(key) ?? null,
    setItem: (key: string, value: string) => cache.set(key, value),
  });
});
afterEach(() => vi.unstubAllGlobals());

describe('per-tab guest transport', () => {
  it('cancels a stalled game renewal without replacing cached progress or blocking retry', async () => {
    startGuest();
    const before = cache.get('lp.guest.v1');
    const controller = new AbortController();
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockImplementationOnce(
          (_url: string, options: RequestInit) =>
            new Promise((_resolve, reject) => {
              options.signal?.addEventListener(
                'abort',
                () => reject(new DOMException('Aborted', 'AbortError')),
                { once: true },
              );
            }),
        )
        .mockResolvedValueOnce(
          Response.json({ result: { leaseSeconds: 12 }, state: { renewed: true } }),
        ),
    );
    const pending = guestApi('/games/heartbeat', { method: 'POST', signal: controller.signal });
    await Promise.resolve();
    controller.abort();
    await expect(pending).rejects.toThrow('Aborted');
    expect(cache.get('lp.guest.v1')).toBe(before);
    await expect(guestApi('/games/heartbeat', { method: 'POST' })).resolves.toEqual({
      leaseSeconds: 12,
    });
  });
  it('serializes concurrent operations using the most recently cached state', async () => {
    startGuest();
    const states: unknown[] = [];
    let step = 0;
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, options: RequestInit) => {
        states.push(JSON.parse(String(options.body)).state);
        const count = ++step;
        await Promise.resolve();
        return Response.json({ result: count, state: { count } });
      }),
    );
    expect(
      await Promise.all([
        guestApi('/sessions', { method: 'POST' }),
        guestApi('/profiles/progress', {}),
      ]),
    ).toEqual([1, 2]);
    expect(states).toEqual([null, { count: 1 }]);
    expect(isGuest()).toBe(true);
    expect(learningAssetUrl('voice', 'prompt-a')).toBe('/api/v1/guest/voice/prompt-a');
  });

  it('preserves the previous cache after network failure and resumes the queue', async () => {
    startGuest();
    const before = cache.get('lp.guest.v1');
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockRejectedValueOnce(new TypeError('offline'))
        .mockResolvedValueOnce(Response.json({ result: 'ok', state: { answer: 1 } })),
    );
    await expect(guestApi('/sessions', { method: 'POST' })).rejects.toThrow('offline');
    expect(cache.get('lp.guest.v1')).toBe(before);
    await expect(guestApi('/sessions', { method: 'POST' })).resolves.toBe('ok');
  });

  it('does not report success when sessionStorage refuses the returned state', async () => {
    startGuest();
    const before = cache.get('lp.guest.v1');
    vi.stubGlobal('sessionStorage', {
      getItem: (key: string) => cache.get(key) ?? null,
      setItem: () => {
        throw new Error('QuotaExceededError');
      },
    });
    vi.stubGlobal(
      'fetch',
      vi.fn().mockResolvedValue(Response.json({ result: 'ok', state: { answer: 1 } })),
    );
    await expect(guestApi('/sessions', { method: 'POST' })).rejects.toThrow('GUEST_CACHE_FULL');
    expect(cache.get('lp.guest.v1')).toBe(before);
    expect(() => startGuest()).toThrow('浏览器临时缓存不可用');
  });

  it('never falls back to household operations when guest cache disappears', async () => {
    startGuest();
    cache.clear();
    const fetcher = vi.fn();
    vi.stubGlobal('fetch', fetcher);
    expect(isGuest()).toBe(true);
    await expect(guestApi('/sessions', { method: 'POST' })).rejects.toThrow('GUEST_CACHE_INVALID');
    expect(fetcher).not.toHaveBeenCalled();
  });

  it('exit prevents an in-flight response resurrecting progress and preserves household retries', async () => {
    startGuest();
    const values: Record<string, string> = {
      'lp.guest.v1': cache.get('lp.guest.v1')!,
      'lp.pending-answer.family': 'family retry',
      'lp.guest.pending-answer.visitor': 'visitor retry',
    };
    const storage = {
      ...values,
      getItem: (key: string) => values[key] ?? null,
      setItem: (key: string, value: string) => {
        values[key] = value;
      },
      removeItem: (key: string) => {
        delete values[key];
      },
    };
    vi.stubGlobal('sessionStorage', storage);
    vi.stubGlobal('window', { location: { reload: vi.fn() } });
    let respond!: (response: Response) => void;
    const fetcher = vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          respond = resolve;
        }),
    );
    vi.stubGlobal('fetch', fetcher);
    const operation = guestApi('/sessions', { method: 'POST' });
    await vi.waitFor(() => expect(fetcher).toHaveBeenCalled());
    leaveGuest();
    respond(Response.json({ result: 'ok', state: { answer: 1 } }));
    await expect(operation).rejects.toThrow('GUEST_EXITED');
    expect(values).toEqual({ 'lp.pending-answer.family': 'family retry' });
  });
});
