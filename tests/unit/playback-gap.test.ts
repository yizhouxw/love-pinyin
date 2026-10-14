import { afterEach, expect, it, vi } from 'vitest';
import { waitForPlaybackGap } from '../../src/platform/audio/playback-gap';
import { highlightedSyllable } from '../../src/domain/daily-reading';
afterEach(() => vi.useRealTimers());
it('waits the selected interval and cancels a pending next sound immediately', async () => {
  vi.useFakeTimers();
  const controller = new AbortController();
  let done = false;
  const waiting = waitForPlaybackGap(1, controller.signal).then(() => {
    done = true;
  });
  await vi.advanceTimersByTimeAsync(999);
  expect(done).toBe(false);
  await vi.advanceTimersByTimeAsync(1);
  await waiting;
  expect(done).toBe(true);
  const pending = waitForPlaybackGap(5, controller.signal);
  const aborted = expect(pending).rejects.toMatchObject({ name: 'AbortError' });
  controller.abort();
  await aborted;
  expect(vi.getTimerCount()).toBe(0);
  await expect(waitForPlaybackGap(0.1, controller.signal)).rejects.toMatchObject({
    name: 'AbortError',
  });
});
it('uses actual uneven speech timestamps and clears during silence and at the end', () => {
  const times = [
    { start: 0.2, end: 0.5 },
    { start: 0.5, end: 1.2 },
    { start: 1.5, end: 1.7 },
  ];
  expect(highlightedSyllable(times, 0.19)).toBe(-1);
  expect(highlightedSyllable(times, 0.3)).toBe(0);
  expect(highlightedSyllable(times, 0.6)).toBe(1);
  expect(highlightedSyllable(times, 1.3)).toBe(-1);
  expect(highlightedSyllable(times, 1.6)).toBe(2);
  expect(highlightedSyllable(times, 1.7)).toBe(-1);
});
