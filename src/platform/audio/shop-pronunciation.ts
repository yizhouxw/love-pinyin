import { createPronunciationService } from './pronunciation-service';
import type { PronunciationTarget } from '../../domain/pronunciation';

/** Replace this composition with a verified acoustic adapter when MATCH-10 has one. */
export function shopPronunciation(targets: readonly PronunciationTarget[]) {
  const mock =
    import.meta.env.DEV && new URLSearchParams(location.search).get('shopRecognition') === 'mock';
  return {
    configured: mock,
    mock,
    service: createPronunciationService({ targets, mode: mock ? 'mock' : 'unavailable' }),
  };
}
