import playback from '../../../content/playback.json';
import type { SpellingClip } from '../../domain/pinyin-spelling';
import { audioPlayer, type PlaybackObserver } from './browser-audio-player';

export function playSpelling(
  parts: (SpellingClip & { position: number })[],
  narrationId: string | null,
  signal: AbortSignal,
  observer?: PlaybackObserver,
) {
  if (!parts.length && narrationId) return audioPlayer.playPrivate(narrationId, signal, observer);
  const clips = narrationId ? [...parts, { kind: 'voice' as const, id: narrationId }] : parts;
  const rhythm = playback.reading.spelling;
  const pauses = clips
    .slice(1)
    .map((_, index) =>
      parts[index]?.position === parts[index + 1]?.position
        ? rhythm.withinSyllableSeconds
        : rhythm.betweenSyllablesSeconds,
    );
  return audioPlayer.playReadingSequence(
    clips,
    signal,
    { ...observer, onSegment: (index) => observer?.onSegment?.(parts[index]?.position ?? -1) },
    pauses,
  );
}
