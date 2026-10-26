import type {
  PronunciationRequest,
  PronunciationService,
  PronunciationTarget,
} from '../../domain/pronunciation';

type Options = Readonly<{
  mode?: 'mock' | 'unavailable';
  targets: readonly PronunciationTarget[];
}>;

/** Explicitly selected simulation or unavailable port. No model loading, audio retention or network access. */
export function createPronunciationService(options: Options): PronunciationService {
  const mode = options.mode ?? 'unavailable';
  const targets = new Map<string, string>();
  for (const target of options.targets) {
    if (!target.id.trim() || !target.pinyin.trim() || targets.has(target.id)) {
      throw new Error('INVALID_PRONUNCIATION_CATALOG');
    }
    targets.set(target.id, target.pinyin.normalize('NFC'));
  }

  async function prepare(request: PronunciationRequest) {
    // Snapshot before yielding so a caller cannot change the request's identity mid-flight.
    const { requestId, targetId, signal } = request;
    if (!requestId.trim() || !targetId.trim()) throw new Error('INVALID_PRONUNCIATION_REQUEST');
    await Promise.resolve();
    if (signal?.aborted) throw new DOMException('Recognition cancelled', 'AbortError');
    const pinyin = targets.get(targetId);
    return {
      context: {
        contractVersion: 1 as const,
        requestId,
        targetId,
        evidence: mode === 'mock' ? ('mock' as const) : ('none' as const),
        toneAssessed: false,
      },
      pinyin,
      reason:
        pinyin === undefined
          ? ('unsupported-target' as const)
          : mode !== 'mock'
            ? ('not-configured' as const)
            : null,
    };
  }

  return {
    async match(request) {
      const { context, reason } = await prepare(request);
      if (request.signal?.aborted) throw new DOMException('Recognition cancelled', 'AbortError');
      return reason
        ? { ...context, status: 'unavailable', reason }
        : { ...context, status: 'matched', reason: null };
    },
    async recognize(request) {
      const { context, pinyin, reason } = await prepare(request);
      if (request.signal?.aborted) throw new DOMException('Recognition cancelled', 'AbortError');
      return reason || pinyin === undefined
        ? {
            ...context,
            status: 'unavailable',
            recognizedPinyin: null,
            reason: reason ?? 'unsupported-target',
          }
        : { ...context, status: 'recognized', recognizedPinyin: pinyin, reason: null };
    },
  };
}
