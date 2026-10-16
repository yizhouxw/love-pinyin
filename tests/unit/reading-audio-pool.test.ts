import { afterEach, describe, expect, it, vi } from 'vitest';
import { ReadingAudioPool } from '../../src/platform/audio/reading-audio-pool';

const response = (text = 'sound') =>
  new Response(text, {
    headers: { 'Content-Length': String(text.length), 'Content-Type': 'audio/mpeg' },
  });
afterEach(() => {
  vi.unstubAllGlobals();
  vi.useRealTimers();
});

describe('bounded encoded reading audio pool', () => {
  it('shares concurrent requests and replays a complete cached asset without networking', async () => {
    const fetcher = vi.fn().mockResolvedValue(response());
    vi.stubGlobal('fetch', fetcher);
    const pool = new ReadingAudioPool();
    const first = pool.get('/api/v1/guest/daily-audio/daily-a1');
    const second = pool.get('/api/v1/guest/daily-audio/daily-a1', true);
    expect(await first).toBe(await second);
    expect(fetcher).toHaveBeenCalledTimes(1);
    expect(await (await pool.get('/api/v1/guest/daily-audio/daily-a1')).text()).toBe('sound');
    expect(fetcher).toHaveBeenCalledTimes(1);
    pool.clear();
  });
  it('retries truncated data once, while a 404 is not retried or cached', async () => {
    const fetcher = vi
      .fn()
      .mockResolvedValueOnce(new Response('cut', { headers: { 'Content-Length': '100' } }))
      .mockResolvedValueOnce(response('complete'))
      .mockResolvedValueOnce(new Response('', { status: 404 }));
    vi.stubGlobal('fetch', fetcher);
    const pool = new ReadingAudioPool();
    expect(await (await pool.get('/one')).text()).toBe('complete');
    await expect(pool.get('/missing')).rejects.toThrow('AUDIO_HTTP_404');
    expect(fetcher).toHaveBeenCalledTimes(3);
    pool.clear();
  });
  it('limits background concurrency, reserves a foreground slot, and discards cancelled late responses', async () => {
    const pending: ((response: Response) => void)[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(() => new Promise<Response>((resolve) => pending.push(resolve))),
    );
    const pool = new ReadingAudioPool();
    pool.prepare(['/a', '/b', '/c', '/d']);
    expect(pending).toHaveLength(2);
    const clicked = pool.get('/d', true);
    const cancelled = expect(clicked).rejects.toMatchObject({ name: 'AbortError' });
    expect(pending).toHaveLength(3);
    pool.clear();
    pending.forEach((resolve) => resolve(response()));
    await cancelled;
    await vi.waitFor(() =>
      expect(pool.status()).toEqual({ total: 0, ready: 0, failed: 0, bytes: 0 }),
    );
  });
  it('evicts encoded bytes within budget and fails oversize assets rather than growing memory', async () => {
    vi.stubGlobal(
      'fetch',
      vi.fn().mockImplementation(() => Promise.resolve(response('abc'))),
    );
    const pool = new ReadingAudioPool(5, 2);
    await pool.get('/a');
    await pool.get('/b');
    await vi.waitFor(() => expect(pool.status().bytes).toBe(3));
    expect(pool.status().bytes).toBeLessThanOrEqual(5);
    pool.clear();
    vi.stubGlobal(
      'fetch',
      vi
        .fn()
        .mockResolvedValue(
          new Response('too big', { headers: { 'Content-Length': String(5 * 1024 * 1024) } }),
        ),
    );
    await expect(pool.get('/huge')).rejects.toThrow('AUDIO_TOO_LARGE');
    pool.clear();
  });
  it('bounds hung downloads to two attempts and releases both timeout timers', async () => {
    vi.useFakeTimers();
    const fetcher = vi.fn(
      (_source, options: RequestInit) =>
        new Promise<Response>((_resolve, reject) =>
          options.signal?.addEventListener(
            'abort',
            () => reject(new DOMException('aborted', 'AbortError')),
            { once: true },
          ),
        ),
    );
    vi.stubGlobal('fetch', fetcher);
    const pool = new ReadingAudioPool(1024, 2, 10);
    const failed = expect(pool.get('/hung')).rejects.toThrow('AUDIO_TIMEOUT');
    await vi.runAllTimersAsync();
    await failed;
    expect(fetcher).toHaveBeenCalledTimes(2);
    expect(vi.getTimerCount()).toBe(0);
    pool.clear();
  });
});
