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
  spellingPauses?: readonly number[],
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
    return joinReadingSamples(decoded, { spellingPauses });
  } catch (error) {
    if (signal.aborted) throw cancelled();
    throw new Error('AUDIO_DECODE_FAILED', { cause: error });
  }
}

/** Ignore low-energy padding without treating a single loud sample as a speech boundary. */
function spellingEdges(channels: Float32Array[], length: number, sampleRate: number) {
  const { edgeWindowSeconds, edgeRmsThreshold } = playback.reading.spelling;
  const window = Math.max(1, Math.round(edgeWindowSeconds * sampleRate));
  const windows = Math.ceil(length / window);
  const audible = (index: number) => {
    const start = index * window;
    const end = Math.min(start + window, length);
    const threshold = edgeRmsThreshold ** 2 * (end - start);
    return channels.some((channel) => {
      let energy = 0;
      for (let i = start; i < end; i++) energy += channel[i]! ** 2;
      return energy >= threshold;
    });
  };
  let first = 0;
  let last = windows - 1;
  while (first < windows && !audible(first)) first++;
  while (last > first && !audible(last)) last--;
  return { first: first * window, last: Math.min(length, (last + 1) * window) - 1 };
}

/** Preserve speech samples and guarded edges, replacing surplus edge silence with a short join. */
export function joinReadingSamples(
  sources: DecodedAudio[],
  options: {
    preserveEdges?: boolean;
    pauseSeconds?: number;
    spellingPauses?: readonly number[];
  } = {},
): CombinedReadingAudio {
  if (!sources.length) throw new Error('AUDIO_DECODE_FAILED');
  const sampleRate = sources[0]!.sampleRate;
  if (!Number.isFinite(sampleRate) || sampleRate <= 0) throw new Error('AUDIO_DECODE_FAILED');
  const { spellingPauses } = options;
  const guardSeconds = spellingPauses
    ? playback.reading.spelling.edgeGuardSeconds
    : playback.reading.edgeGuardSeconds;
  const guard = Math.round(guardSeconds * sampleRate);
  const fade = spellingPauses
    ? Math.round(playback.reading.spelling.edgeFadeSeconds * sampleRate)
    : 0;
  const defaultPause = options.pauseSeconds ?? playback.reading.wordBoundarySilenceSeconds;
  const clips = sources.map((source) => {
    if (source.sampleRate !== sampleRate || !source.length || !source.numberOfChannels)
      throw new Error('AUDIO_DECODE_FAILED');
    const channels = Array.from({ length: source.numberOfChannels }, (_, index) =>
      source.getChannelData(index),
    );
    if (options.preserveEdges)
      return { channels, start: 0, end: source.length, leading: 0, trailing: 0 };
    let first = 0;
    let last = source.length - 1;
    if (spellingPauses) {
      ({ first, last } = spellingEdges(channels, source.length, sampleRate));
    } else {
      // Inspect every channel so a quiet channel cannot hide another channel's speech edge.
      const audible = (index: number) =>
        channels.some((channel) => Math.abs(channel[index]!) >= playback.reading.silenceThreshold);
      while (first < source.length && !audible(first)) first++;
      while (last >= first && !audible(last)) last--;
    }
    // Never turn an unexpectedly quiet file into an empty or shortened sound.
    if (first > last) return { channels, start: 0, end: source.length, leading: 0, trailing: 0 };
    const start = Math.max(0, first - guard);
    const end = Math.min(source.length, last + guard + 1);
    return { channels, start, end, leading: first - start, trailing: end - last - 1 };
  });
  const joins = clips.map((clip, index) => {
    const next = clips[index + 1];
    if (!next) return 0;
    const boundary = Math.round((spellingPauses?.[index] ?? defaultPause) * sampleRate);
    return Math.max(0, boundary - clip.trailing - next.leading);
  });
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
    const fadeFrames = Math.min(fade, Math.floor((clip.end - clip.start) / 2));
    for (let sourceFrame = clip.start; sourceFrame < clip.end; sourceFrame++, frame++) {
      const gain = fadeFrames
        ? Math.min(
            1,
            (sourceFrame - clip.start) / fadeFrames,
            (clip.end - 1 - sourceFrame) / fadeFrames,
          )
        : 1;
      for (let channel = 0; channel < channels; channel++) {
        const source = clip.channels[channel] ?? clip.channels[0]!;
        const sample = Math.max(-1, Math.min(1, source[sourceFrame]! * gain));
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
