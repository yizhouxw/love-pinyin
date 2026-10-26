import { shopRules } from '../../domain/pinyin-shop';
import { createPronunciationService } from './pronunciation-service';
import type { PronunciationTarget } from '../../domain/pronunciation';

/** Explicitly configured shop simulation; never inferred from a real service failure. */
export function shopPronunciation(
  targets: readonly PronunciationTarget[],
  mode: 'mock' | 'unavailable' = shopRules.recognitionMode === 'mock' ? 'mock' : 'unavailable',
) {
  return {
    configured: mode === 'mock',
    mock: mode === 'mock',
    service: createPronunciationService({ targets, mode }),
  };
}
