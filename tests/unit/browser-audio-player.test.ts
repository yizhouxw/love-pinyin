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
