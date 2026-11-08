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
  if (parts.length === 1 && !narrationId && parts[0]?.kind === 'daily-audio') {
    const part = parts[0];
    return audioPlayer.playDaily(part.id, signal, {
      ...observer,
      onStart: () => observer?.onSegment?.(part.position),
    });
  }
  const clips = narrationId ? [...parts, { kind: 'voice' as const, id: narrationId }] : parts;
  return audioPlayer.playReadingSequence(
    clips,
    signal,
    { ...observer, onSegment: (index) => observer?.onSegment?.(parts[index]?.position ?? -1) },
    playback.reading.spellingPauseSeconds,
  );
}
