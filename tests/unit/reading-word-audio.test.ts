import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  combineReadingAudio,
  joinReadingSamples,
  readingSegmentAt,
} from '../../src/platform/audio/reading-word-audio';

function recording(channels: Float32Array[], sampleRate = 1000): AudioBuffer {
  return {
    length: channels[0]!.length,
    sampleRate,
    numberOfChannels: channels.length,
    getChannelData: (index: number) => channels[index]!,
  } as AudioBuffer;
}
function paddedSpeech(leading = 300, trailing = 300): Float32Array {
  const values = new Float32Array(leading + 400 + trailing);
  values.fill(0.25, leading, leading + 400);
  return values;
}

afterEach(() => vi.unstubAllGlobals());

describe('current-item standard audio composition', () => {
  it('removes surplus edge silence, keeps guards and uses a 100ms speech boundary without changing speech samples', async () => {
    const result = joinReadingSamples([recording([paddedSpeech()]), recording([paddedSpeech()])]);
    const view = new DataView(await result.blob.arrayBuffer());
    expect(result.blob.type).toBe('audio/wav');
    expect(view.getUint32(24, true)).toBe(1000);
    expect(view.getUint32(40, true)).toBe(980 * 2);
    expect(result.segments).toEqual([
      { startSeconds: 0, endSeconds: 0.48 },
      { startSeconds: 0.5, endSeconds: 0.98 },
    ]);
    const samples = new Int16Array(await result.blob.slice(44).arrayBuffer());
    expect([...samples.slice(0, 40)].every((value) => value === 0)).toBe(true);
    expect([...samples.slice(40, 440)].every((value) => value === 8192)).toBe(true);
    expect([...samples.slice(440, 540)].every((value) => value === 0)).toBe(true);
    expect([...samples.slice(540, 940)].every((value) => value === 8192)).toBe(true);
    expect(readingSegmentAt(result.segments, 0)).toBe(0);
    expect(readingSegmentAt(result.segments, 0.48)).toBe(-1);
    expect(readingSegmentAt(result.segments, 0.5)).toBe(1);
    expect(readingSegmentAt(result.segments, 0.98)).toBe(-1);
  });

  it('retains low-level consonant edges and never cuts speech that reaches an original edge', async () => {
    const speech = paddedSpeech(0, 0);
    speech[0] = 0.0006;
    speech[speech.length - 1] = 0.0006;
    const result = joinReadingSamples([recording([speech]), recording([speech])]);
    const samples = new Int16Array(await result.blob.slice(44).arrayBuffer());
    expect(samples).toHaveLength(900);
    expect(samples[0]).toBe(20);
    expect(samples[399]).toBe(20);
    expect(samples[500]).toBe(20);
    expect(samples[899]).toBe(20);
  });

  it('preserves quiet/unexpectedly silent recordings in full instead of dropping their duration', async () => {
    const quiet = new Float32Array(750).fill(0.0004);
    const result = joinReadingSamples([recording([quiet])]);
    expect(result.segments).toEqual([{ startSeconds: 0, endSeconds: 0.75 }]);
    expect(result.blob.size).toBe(44 + 750 * 2);
  });

  it('preserves stereo channels without cancelling opposite-phase speech and promotes mono clips', async () => {
    const positive = paddedSpeech();
    const negative = positive.map((value) => -value);
    const result = joinReadingSamples([recording([positive, negative]), recording([positive])]);
    const view = new DataView(await result.blob.arrayBuffer());
    expect(view.getUint16(22, true)).toBe(2);
    expect(view.getUint16(32, true)).toBe(4);
    expect(view.getInt16(44 + 40 * 4, true)).toBe(8192);
    expect(view.getInt16(44 + 40 * 4 + 2, true)).toBe(-8192);
    expect(view.getInt16(44 + 540 * 4, true)).toBe(8192);
    expect(view.getInt16(44 + 540 * 4 + 2, true)).toBe(8192);
  });

  it('rejects empty sources or inconsistent decode rates', () => {
    expect(() => joinReadingSamples([])).toThrow('AUDIO_DECODE_FAILED');
    expect(() => joinReadingSamples([recording([new Float32Array(0)])])).toThrow(
      'AUDIO_DECODE_FAILED',
    );
    expect(() =>
      joinReadingSamples([recording([paddedSpeech()]), recording([paddedSpeech()], 2000)]),
    ).toThrow('AUDIO_DECODE_FAILED');
  });

  it('decodes only requested clips and stops before the next clip when cancelled during a decode', async () => {
    let finishDecode!: (value: AudioBuffer) => void;
    const decode = vi.fn(() => new Promise<AudioBuffer>((resolve) => (finishDecode = resolve)));
    vi.stubGlobal(
      'OfflineAudioContext',
      class {
        decodeAudioData = decode;
      },
    );
    const controller = new AbortController();
    const prepared = combineReadingAudio([new Blob(['one']), new Blob(['two'])], controller.signal);
    const rejected = expect(prepared).rejects.toMatchObject({ name: 'AbortError' });
    await vi.waitFor(() => expect(decode).toHaveBeenCalledOnce());
    controller.abort();
    finishDecode(recording([paddedSpeech()]));
    await rejected;
    expect(decode).toHaveBeenCalledOnce();
  });

  it('reports a decode failure without returning a partially assembled word', async () => {
    const decode = vi
      .fn()
      .mockResolvedValueOnce(recording([paddedSpeech()]))
      .mockRejectedValueOnce(new Error('bad mp3'));
    vi.stubGlobal(
      'OfflineAudioContext',
      class {
        decodeAudioData = decode;
      },
    );
    await expect(
      combineReadingAudio([new Blob(['one']), new Blob(['two'])], new AbortController().signal),
    ).rejects.toThrow('AUDIO_DECODE_FAILED');
    expect(decode).toHaveBeenCalledTimes(2);
  });
});

describe('DAILY-11 character pauses', () => {
  it('preserves every original sample and inserts exactly 400ms per boundary, with silence unhighlighted', async () => {
    const { spaceCharacterSamples } = await import('../../src/platform/audio/reading-word-audio');
    const original = Float32Array.from({ length: 1000 }, (_, i) => (i % 10) / 20);
    const result = spaceCharacterSamples(recording([original]), [
      { start: 0.1, end: 0.35 },
      { start: 0.4, end: 0.6 },
      { start: 0.65, end: 0.95 },
    ]);
    const samples = new Int16Array(await result.blob.slice(44).arrayBuffer());
    expect(samples.length).toBe(1800);
    const restored = [
      ...samples.slice(0, 400),
      ...samples.slice(800, 1050),
      ...samples.slice(1450),
    ];
    expect(restored).toEqual([...original].map((v) => Math.round(v * 32767)));
    expect([...samples.slice(400, 800), ...samples.slice(1050, 1450)].every((v) => v === 0)).toBe(
      true,
    );
    expect(result.segments[1]!.startSeconds).toBeCloseTo(0.8);
    expect(readingSegmentAt(result.segments, 0.6)).toBe(-1);
    expect(readingSegmentAt(result.segments, 0.85)).toBe(1);
  });
  it('rejects missing, out of bounds or coincident character onsets', async () => {
    const { spaceCharacterSamples } = await import('../../src/platform/audio/reading-word-audio');
    for (const spans of [
      [],
      [{ start: 0, end: 2 }],
      [
        { start: 0, end: 0.2 },
        { start: 0, end: 0.3 },
      ],
    ])
      expect(() => spaceCharacterSamples(recording([paddedSpeech()]), spans)).toThrow(
        'AUDIO_TIMELINE_INVALID',
      );
  });
});
