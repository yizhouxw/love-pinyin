import playback from '../../../content/playback.json';

export type ReadingSegment = { startSeconds: number; endSeconds: number };
export type CombinedReadingAudio = { blob: Blob; segments: ReadingSegment[] };
type DecodedAudio = Pick<
  AudioBuffer,
  'sampleRate' | 'length' | 'numberOfChannels' | 'getChannelData'
>;

const cancelled = () => new DOMException('Reading audio cancelled.', 'AbortError');

/** Decode only the requested item; playback still uses the activated HTML media element. */
export async function combineReadingAudio(
  sources: Blob[],
  signal: AbortSignal,
): Promise<CombinedReadingAudio> {
  if (signal.aborted) throw cancelled();
  try {
    const decoder = new OfflineAudioContext(1, 1, 24000);
    const decoded: AudioBuffer[] = [];
    for (const source of sources) {
      const bytes = await source.arrayBuffer();
      if (signal.aborted) throw cancelled();
      decoded.push(await decoder.decodeAudioData(bytes));
      if (signal.aborted) throw cancelled();
    }
    return joinReadingSamples(decoded);
  } catch (error) {
    if (signal.aborted) throw cancelled();
    throw new Error('AUDIO_DECODE_FAILED', { cause: error });
  }
}

/** Preserve speech samples and guarded edges, replacing surplus edge silence with a short join. */
export function joinReadingSamples(
  sources: DecodedAudio[],
  options: { preserveEdges?: boolean; pauseSeconds?: number } = {},
): CombinedReadingAudio {
  if (!sources.length) throw new Error('AUDIO_DECODE_FAILED');
  const sampleRate = sources[0]!.sampleRate;
  if (!Number.isFinite(sampleRate) || sampleRate <= 0) throw new Error('AUDIO_DECODE_FAILED');
  const guard = Math.round(playback.reading.edgeGuardSeconds * sampleRate);
  const boundary = Math.round(
    (options.pauseSeconds ?? playback.reading.wordBoundarySilenceSeconds) * sampleRate,
  );
  const clips = sources.map((source) => {
    if (source.sampleRate !== sampleRate || !source.length || !source.numberOfChannels)
      throw new Error('AUDIO_DECODE_FAILED');
    const channels = Array.from({ length: source.numberOfChannels }, (_, index) =>
      source.getChannelData(index),
    );
    if (options.preserveEdges)
      return { channels, start: 0, end: source.length, leading: 0, trailing: 0 };
    // Inspect every channel so a quiet channel cannot hide another channel's speech edge.
    const audible = (index: number) =>
      channels.some((channel) => Math.abs(channel[index]!) >= playback.reading.silenceThreshold);
    let first = 0;
    let last = source.length - 1;
    while (first < source.length && !audible(first)) first++;
    while (last >= first && !audible(last)) last--;
    // Never turn an unexpectedly quiet file into an empty or shortened sound.
    if (first > last) return { channels, start: 0, end: source.length, leading: 0, trailing: 0 };
    const start = Math.max(0, first - guard);
    const end = Math.min(source.length, last + guard + 1);
    return { channels, start, end, leading: first - start, trailing: end - last - 1 };
  });
  const joins = clips.map((clip, index) =>
    index < clips.length - 1
      ? Math.max(0, boundary - clip.trailing - clips[index + 1]!.leading)
      : 0,
  );
  const frames = clips.reduce(
    (total, clip, index) => total + clip.end - clip.start + joins[index]!,
    0,
  );
  const channels = Math.max(...clips.map((clip) => clip.channels.length));
  const bytesPerFrame = channels * 2;
  const bytes = new Uint8Array(44 + frames * bytesPerFrame);
  const view = new DataView(bytes.buffer);
  const label = (offset: number, value: string) =>
    [...value].forEach((character, index) =>
      view.setUint8(offset + index, character.charCodeAt(0)),
    );
  label(0, 'RIFF');
  view.setUint32(4, bytes.length - 8, true);
  label(8, 'WAVE');
  label(12, 'fmt ');
  view.setUint32(16, 16, true);
  view.setUint16(20, 1, true);
  view.setUint16(22, channels, true);
  view.setUint32(24, sampleRate, true);
  view.setUint32(28, sampleRate * bytesPerFrame, true);
  view.setUint16(32, bytesPerFrame, true);
  view.setUint16(34, 16, true);
  label(36, 'data');
  view.setUint32(40, frames * bytesPerFrame, true);
  const segments: ReadingSegment[] = [];
  let frame = 0;
  for (const [index, clip] of clips.entries()) {
    const startSeconds = frame / sampleRate;
    for (let sourceFrame = clip.start; sourceFrame < clip.end; sourceFrame++, frame++) {
      for (let channel = 0; channel < channels; channel++) {
        const source = clip.channels[channel] ?? clip.channels[0]!;
        const sample = Math.max(-1, Math.min(1, source[sourceFrame]!));
        view.setInt16(
          44 + frame * bytesPerFrame + channel * 2,
          Math.round(sample * (sample < 0 ? 32768 : 32767)),
          true,
        );
      }
    }
    segments.push({ startSeconds, endSeconds: frame / sampleRate });
    frame += joins[index]!;
  }
  return { blob: new Blob([bytes], { type: 'audio/wav' }), segments };
}

/** Insert pauses at aligned character boundaries without removing any original samples. */
export function spaceCharacterSamples(
  source: DecodedAudio,
  timings: { start: number; end: number }[],
): CombinedReadingAudio {
  const duration = source.length / source.sampleRate;
  if (
    !timings.length ||
    timings.some(
      (t, index) =>
        !Number.isFinite(t.start) ||
        !Number.isFinite(t.end) ||
        t.start < 0 ||
        t.end <= t.start ||
        t.end > duration + 0.002 ||
        (index > 0 && t.start <= timings[index - 1]!.start),
    )
  )
    throw new Error('AUDIO_TIMELINE_INVALID');
  const starts = [
    0,
    ...timings.slice(1).map((t) => Math.round(t.start * source.sampleRate)),
    source.length,
  ];
  const chunks = timings.map((_, index) => ({
    sampleRate: source.sampleRate,
    numberOfChannels: source.numberOfChannels,
    length: starts[index + 1]! - starts[index]!,
    getChannelData: (channel: number) =>
      source.getChannelData(channel).subarray(starts[index], starts[index + 1]),
  }));
  const pause = playback.reading.characterPauseSeconds;
  const result = joinReadingSamples(chunks, { preserveEdges: true, pauseSeconds: pause });
  return {
    ...result,
    segments: timings.map((t, index) => ({
      startSeconds: t.start + index * pause,
      endSeconds: Math.min(t.end, timings[index + 1]?.start ?? duration) + index * pause,
    })),
  };
}

export async function spaceReadingCharacters(
  source: Blob,
  timings: { start: number; end: number }[],
  signal: AbortSignal,
) {
  const decoder = new OfflineAudioContext(1, 1, 24000);
  if (signal.aborted) throw cancelled();
  const decoded = await decoder.decodeAudioData(await source.arrayBuffer());
  if (signal.aborted) throw cancelled();
  return spaceCharacterSamples(decoded, timings);
}

export function readingSegmentAt(segments: ReadingSegment[], seconds: number): number {
  return segments.findIndex(
    (segment) => seconds >= segment.startSeconds && seconds < segment.endSeconds,
  );
}
