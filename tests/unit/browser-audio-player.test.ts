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
  vi.useRealTimers();
  FakeAudio.instances = [];
});

describe('BrowserAudioPlayer', () => {
  it('bounds initial loading and playback stalls, releasing timers and the active source', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('Audio', FakeAudio);
    const player = new BrowserAudioPlayer();
    const loading = expect(player.play('audio-final-a')).rejects.toThrow('AUDIO_TIMEOUT');
    await vi.advanceTimersByTimeAsync(30000);
    await loading;
    expect(FakeAudio.instances[0]!.src).toBe('');
    const stalled = expect(player.playPrivate('prompt-question')).rejects.toThrow('AUDIO_STALLED');
    const audio = FakeAudio.instances[0]! as FakeAudio & { currentTime: number };
    audio.currentTime = 0;
    audio.dispatchEvent(new Event('playing'));
    await vi.advanceTimersByTimeAsync(10000);
    audio.currentTime = 1;
    audio.dispatchEvent(new Event('timeupdate'));
    await vi.advanceTimersByTimeAsync(10000);
    expect(audio.src).not.toBe('');
    // Repeated timeupdate at the same position must not hide a stall.
    audio.dispatchEvent(new Event('timeupdate'));
    await vi.advanceTimersByTimeAsync(5000);
    await stalled;
    expect(audio.src).toBe('');
    expect(vi.getTimerCount()).toBe(0);
  });
  it('uses an encoded same-origin allowlist URL and stops the prior sound before replay', async () => {
    vi.stubGlobal('Audio', FakeAudio);
    const player = new BrowserAudioPlayer();
    const first = player.play('audio-final-a');
    const firstStopped = expect(first).rejects.toMatchObject({ name: 'AbortError' });
    const firstAudio = FakeAudio.instances[0]!;
    const firstSource = firstAudio.src;
    const second = player.play('audio-final-o');
    const secondAudio = FakeAudio.instances[0]!;

    expect(new URL(firstSource, 'https://family.local').origin).toBe('https://family.local');
    expect(firstSource).toBe('/api/v1/audio/audio-final-a');
    await firstStopped;
    expect(secondAudio).toBe(firstAudio);
    expect(FakeAudio.instances).toHaveLength(1);
    expect(secondAudio.src).toBe('/api/v1/audio/audio-final-o');
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

it('plays a multi-syllable item from one WAV and reports segments only from actual media time', async () => {
  const attributes = new Map<string, string>();
  class ReadingAudio extends FakeAudio {
    currentTime = 0;
    setAttribute(name: string, value: string) {
      attributes.set(name, value);
    }
    override removeAttribute(name: string) {
      attributes.delete(name);
      super.removeAttribute(name);
    }
  }
  vi.stubGlobal('Audio', ReadingAudio);
  vi.stubGlobal('document', { hidden: false });
  const sample = new Float32Array(1000);
  sample.fill(0.25, 300, 700);
  const decode = vi.fn().mockResolvedValue({
    sampleRate: 1000,
    length: sample.length,
    numberOfChannels: 1,
    getChannelData: () => sample,
  });
  vi.stubGlobal(
    'OfflineAudioContext',
    class {
      decodeAudioData = decode;
    },
  );
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(() => Promise.resolve(new Response('mp3'))),
  );
  let frame: FrameRequestCallback | undefined;
  vi.stubGlobal('requestAnimationFrame', (callback: FrameRequestCallback) => {
    frame = callback;
    return 1;
  });
  vi.stubGlobal('cancelAnimationFrame', () => {
    frame = undefined;
  });
  const player = new BrowserAudioPlayer();
  const segment = vi.fn();
  const playing = player.playDailySequence(['daily-da4', 'daily-di4'], undefined, {
    onSegment: segment,
  });
  const media = FakeAudio.instances[0]! as ReadingAudio;
  media.dispatchEvent(new Event('playing'));
  media.dispatchEvent(new Event('ended'));
  expect(segment).not.toHaveBeenCalled();
  await vi.waitFor(() => expect(attributes.has('data-learning-sources')).toBe(true));
  expect(JSON.parse(attributes.get('data-learning-sources')!)).toEqual([
    '/api/v1/daily-audio/daily-da4',
    '/api/v1/daily-audio/daily-di4',
  ]);
  expect(decode).toHaveBeenCalledTimes(2);
  media.dispatchEvent(new Event('playing'));
  expect(segment).toHaveBeenLastCalledWith(0);
  media.currentTime = 0.49;
  frame!(0);
  expect(segment).toHaveBeenLastCalledWith(-1);
  media.currentTime = 0.5;
  frame!(0);
  expect(segment).toHaveBeenLastCalledWith(1);
  media.dispatchEvent(new Event('ended'));
  await playing;
  expect(segment).toHaveBeenLastCalledWith(-1);
  expect(frame).toBeUndefined();
  expect(FakeAudio.instances).toHaveLength(1);
  expect(media.src).toBe('');
  player.releaseReading();
});

it('does not attach or play an obsolete combined word after cancellation during decoding', async () => {
  const attributes = new Map<string, string>();
  class ReadingAudio extends FakeAudio {
    setAttribute(name: string, value: string) {
      attributes.set(name, value);
    }
    override removeAttribute(name: string) {
      attributes.delete(name);
      super.removeAttribute(name);
    }
  }
  vi.stubGlobal('Audio', ReadingAudio);
  vi.stubGlobal('document', { hidden: false });
  let finishDecode!: (value: AudioBuffer) => void;
  const decode = vi.fn(
    () =>
      new Promise<AudioBuffer>((resolve) => {
        finishDecode = resolve;
      }),
  );
  vi.stubGlobal(
    'OfflineAudioContext',
    class {
      decodeAudioData = decode;
    },
  );
  vi.stubGlobal(
    'fetch',
    vi.fn().mockImplementation(() => Promise.resolve(new Response('mp3'))),
  );
  const player = new BrowserAudioPlayer();
  const controller = new AbortController();
  const playing = player.playDailySequence(['daily-da4', 'daily-di4'], controller.signal);
  const rejected = expect(playing).rejects.toMatchObject({ name: 'AbortError' });
  await vi.waitFor(() => expect(decode).toHaveBeenCalledOnce());
  controller.abort();
  await rejected;
  finishDecode({} as AudioBuffer);
  await new Promise((resolve) => setTimeout(resolve, 0));
  expect(decode).toHaveBeenCalledOnce();
  expect(attributes.has('data-learning-source')).toBe(false);
  expect(FakeAudio.instances[0]!.src).toBe('');
  expect(FakeAudio.instances[0]!.paused).toBe(true);
  player.releaseReading();
});
