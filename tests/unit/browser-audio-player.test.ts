import { afterEach, describe, expect, it, vi } from 'vitest';
import { BrowserAudioPlayer } from '../../src/platform/audio/browser-audio-player';

class FakeAudio extends EventTarget {
  static instances: FakeAudio[] = [];
  src: string;
  preload = '';
  paused = true;

  constructor(source: string) {
    super();
    this.src = source;
    FakeAudio.instances.push(this);
  }

  play(): Promise<void> {
    this.paused = false;
    return Promise.resolve();
  }

  pause(): void {
    this.paused = true;
  }

  getAttribute(name: string): string | null {
    return name === 'src' ? this.src : null;
  }

  removeAttribute(name: string): void {
    if (name === 'src') this.src = '';
  }

  load(): void {}
}

afterEach(() => {
  vi.unstubAllGlobals();
  FakeAudio.instances = [];
});

describe('BrowserAudioPlayer', () => {
  it('uses an encoded same-origin allowlist URL and stops the prior sound before replay', async () => {
    vi.stubGlobal('Audio', FakeAudio);
    const player = new BrowserAudioPlayer();
    const first = player.play('audio-final-a');
    const firstStopped = expect(first).rejects.toMatchObject({ name: 'AbortError' });
    const firstAudio = FakeAudio.instances[0]!;
    const firstSource = firstAudio.src;
    const second = player.play('audio-final-o');
    const secondAudio = FakeAudio.instances[1]!;

    expect(new URL(firstSource, 'https://family.local').origin).toBe('https://family.local');
    expect(firstSource).toBe('/api/v1/audio/audio-final-a');
    expect(firstAudio.paused).toBe(true);
    expect(firstAudio.src).toBe('');
    expect(secondAudio.paused).toBe(false);

    secondAudio.dispatchEvent(new Event('ended'));
    await Promise.all([firstStopped, second]);
    expect(secondAudio.src).toBe('');
    expect(secondAudio.paused).toBe(true);
  });

  it('stops and releases media immediately when an AbortSignal fires', async () => {
    vi.stubGlobal('Audio', FakeAudio);
    const player = new BrowserAudioPlayer();
    const controller = new AbortController();
    const result = player.play('audio-final-a', controller.signal);
    const rejected = expect(result).rejects.toMatchObject({ name: 'AbortError' });

    controller.abort();
    await rejected;
    expect(FakeAudio.instances[0]!.paused).toBe(true);
    expect(FakeAudio.instances[0]!.src).toBe('');
  });

  it('reports media decode failures without keeping a source alive', async () => {
    vi.stubGlobal(
      'Audio',
      class extends FakeAudio {
        override play(): Promise<void> {
          return Promise.reject(new Error('unsupported media'));
        }
      },
    );
    const player = new BrowserAudioPlayer();
    await expect(player.play('audio-final-a')).rejects.toThrow('AUDIO_UNAVAILABLE');
    expect(FakeAudio.instances[0]!.src).toBe('');
    expect(FakeAudio.instances[0]!.paused).toBe(true);
  });

  it('clears the active source when the browser raises a synchronous play error', async () => {
    vi.stubGlobal(
      'Audio',
      class extends FakeAudio {
        override play(): Promise<void> {
          throw new Error('gesture denied');
        }
      },
    );
    const player = new BrowserAudioPlayer();
    await expect(player.play('audio-final-a')).rejects.toThrow('AUDIO_UNAVAILABLE');
    expect(FakeAudio.instances[0]!.src).toBe('');
    expect(FakeAudio.instances[0]!.paused).toBe(true);
  });
});

it('notifies actual playback position only after playing and releases updates on abort', async () => {
  vi.stubGlobal('Audio', FakeAudio);
  let frame: FrameRequestCallback | undefined;
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    frame = callback;
    return 1;
  });
  vi.stubGlobal('cancelAnimationFrame', () => {
    frame = undefined;
  });
  const player = new BrowserAudioPlayer();
  const controller = new AbortController();
  const started = vi.fn();
  const times: number[] = [];
  const result = player.playPrivate('ui-word-example', controller.signal, {
    onStart: started,
    onTime: (time) => times.push(time),
  });
  const rejected = expect(result).rejects.toMatchObject({ name: 'AbortError' });
  const media = FakeAudio.instances[0]! as FakeAudio & { currentTime: number };
  media.currentTime = 0.3;
  expect(started).not.toHaveBeenCalled();
  expect(times).toEqual([]);
  media.dispatchEvent(new Event('playing'));
  expect(started).toHaveBeenCalledOnce();
  expect(times).toEqual([0.3]);
  media.currentTime = 0.8;
  const tick = frame!;
  frame = undefined;
  tick(0);
  expect(times).toEqual([0.3, 0.8]);
  controller.abort();
  await rejected;
  expect(frame).toBeUndefined();
  media.dispatchEvent(new Event('playing'));
  expect(times).toEqual([0.3, 0.8]);
});

it('buffers the complete daily clip before playing, ignores primer events, reuses the element and replays without a request', async () => {
  const attributes = new Map<string, string>();
  class ReadingAudio extends FakeAudio {
    currentTime = 0;
    setAttribute(name: string, value: string) {
      attributes.set(name, value);
    }
    override getAttribute(name: string) {
      return name === 'src' ? this.src : (attributes.get(name) ?? null);
    }
    override removeAttribute(name: string) {
      attributes.delete(name);
      super.removeAttribute(name);
    }
  }
  vi.stubGlobal('Audio', ReadingAudio);
  vi.stubGlobal('document', { hidden: false });
  let deliver!: (response: Response) => void;
  const fetcher = vi.fn(
    () =>
      new Promise<Response>((resolve) => {
        deliver = resolve;
      }),
  );
  vi.stubGlobal('fetch', fetcher);
  const created = vi.spyOn(URL, 'createObjectURL');
  const revoked = vi.spyOn(URL, 'revokeObjectURL');
  const player = new BrowserAudioPlayer();
  const started = vi.fn();
  const first = player.playDaily('daily-a1', undefined, { onStart: started });
  const media = FakeAudio.instances[0]! as ReadingAudio;
  media.dispatchEvent(new Event('playing'));
  media.dispatchEvent(new Event('ended'));
  expect(started).not.toHaveBeenCalled();
  expect(attributes.has('data-learning-source')).toBe(false);
  deliver(new Response('complete encoded fixture', { headers: { 'Content-Type': 'audio/mpeg' } }));
  await vi.waitFor(() =>
    expect(attributes.get('data-learning-source')).toBe('/api/v1/daily-audio/daily-a1'),
  );
  media.dispatchEvent(new Event('playing'));
  expect(started).toHaveBeenCalledOnce();
  media.dispatchEvent(new Event('ended'));
  await first;
  expect(media.src).toBe('');
  const replay = player.playDaily('daily-a1');
  await vi.waitFor(() => expect(attributes.has('data-learning-source')).toBe(true));
  expect(FakeAudio.instances).toHaveLength(1);
  expect(fetcher).toHaveBeenCalledTimes(1);
  const stopped = expect(replay).rejects.toMatchObject({ name: 'AbortError' });
  player.releaseReading();
  await stopped;
  expect(media.src).toBe('');
  expect(revoked.mock.calls.map((call) => call[0]).sort()).toEqual(
    created.mock.results.map((result) => result.value as string).sort(),
  );
  created.mockRestore();
  revoked.mockRestore();
});

it('reports a daily media gesture rejection without pretending the demonstration completed', async () => {
  class DeniedAudio extends FakeAudio {
    override play(): Promise<void> {
      return Promise.reject(new DOMException('tap required', 'NotAllowedError'));
    }
  }
  vi.stubGlobal('Audio', DeniedAudio);
  vi.stubGlobal('document', { hidden: false });
  vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response('fixture')));
  const player = new BrowserAudioPlayer();
  const started = vi.fn();
  await expect(player.playDaily('daily-a1', undefined, { onStart: started })).rejects.toThrow(
    'AUDIO_GESTURE_REQUIRED',
  );
  expect(started).not.toHaveBeenCalled();
  expect(FakeAudio.instances[0]!.src).toBe('');
  player.releaseReading();
});
