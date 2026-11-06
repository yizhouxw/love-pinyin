import { afterEach, describe, expect, it, vi } from 'vitest';
import { WordPlayback } from '../../src/platform/audio/word-playback';

const settle = async () => {
  await Promise.resolve();
  await Promise.resolve();
};
afterEach(() => vi.useRealTimers());
describe('finite word playback queue', () => {
  it('plays in order with a silent gap and ends without looping', async () => {
    vi.useFakeTimers();
    const play = vi.fn().mockResolvedValue(undefined);
    const queue = new WordPlayback(play);
    queue.playSequence(['one', 'two'], 2, true);
    await settle();
    expect(queue.snapshot()).toMatchObject({ playingId: 'one', waiting: true, continuous: true });
    expect(play).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1999);
    expect(play).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(play.mock.calls.map((call) => call[0])).toEqual(['one', 'two']);
    expect(queue.snapshot().playingId).toBeNull();
    await vi.advanceTimersByTimeAsync(10000);
    expect(play).toHaveBeenCalledTimes(2);
  });
  it('cancels waiting and keeps a newer point-read safe from stale completions', async () => {
    vi.useFakeTimers();
    const play = vi.fn().mockResolvedValue(undefined);
    const queue = new WordPlayback(play);
    queue.playSequence(['one', 'two'], 2, true);
    await settle();
    queue.play('manual');
    await settle();
    await vi.advanceTimersByTimeAsync(3000);
    expect(play.mock.calls.map((call) => call[0])).toEqual(['one', 'manual']);
    let finish!: () => void;
    play.mockImplementationOnce(
      () =>
        new Promise<void>((resolve) => {
          finish = resolve;
        }),
    );
    queue.playSequence(['old', 'never']);
    queue.play('new');
    finish();
    await settle();
    expect(play.mock.calls.map((call) => call[0])).not.toContain('never');
    expect(queue.snapshot().failureId).toBeNull();
  });
  it('stops on failure and retries from that word with the rest of the queue', async () => {
    const play = vi
      .fn()
      .mockResolvedValueOnce(undefined)
      .mockRejectedValueOnce(new Error('offline'))
      .mockResolvedValue(undefined);
    const queue = new WordPlayback(play);
    queue.playSequence(['one', 'two', 'three'], 0, true);
    await settle();
    expect(queue.snapshot()).toMatchObject({ failureId: 'two', playingId: null });
    queue.retry();
    await settle();
    expect(play.mock.calls.map((call) => call[0])).toEqual(['one', 'two', 'two', 'three']);
    queue.stop();
    queue.retry();
    expect(play).toHaveBeenCalledTimes(4);
  });
  it('passes cancellation to active audio and never proceeds after stop', async () => {
    let signal!: AbortSignal;
    let finish!: () => void;
    const play = vi.fn((_id: string, value: AbortSignal) => {
      signal = value;
      return new Promise<void>((resolve) => {
        finish = resolve;
      });
    });
    const queue = new WordPlayback(play);
    queue.playSequence(['one', 'two']);
    queue.stop();
    expect(signal.aborted).toBe(true);
    finish();
    await settle();
    expect(play).toHaveBeenCalledTimes(1);
    expect(queue.snapshot().playingId).toBeNull();
  });
});
