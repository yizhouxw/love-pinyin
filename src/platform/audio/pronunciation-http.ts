import type { PronunciationRequest, PronunciationService } from '../../domain/pronunciation';
import type {
  PronunciationAssessment,
  PronunciationHistory,
} from '../../domain/pronunciation-practice';
import { isGuest } from '../guest';

const prefix = () => `/api/v1/${isGuest() ? 'guest/' : ''}pronunciation`;

/** Bounded one-request cache lets MATCH-10's two methods share one acoustic evaluation. */
export function createHttpPronunciationService(): PronunciationService & {
  assess(request: PronunciationRequest): Promise<PronunciationAssessment>;
} {
  let previous: PronunciationRequest | undefined;
  let pending: Promise<PronunciationAssessment> | undefined;
  function assess(request: PronunciationRequest): Promise<PronunciationAssessment> {
    if (!request.requestId.trim() || !request.targetId.trim())
      throw new Error('INVALID_PRONUNCIATION_REQUEST');
    if (previous === request && pending) return pending;
    previous = request;
    pending = (async () => {
      const { requestId, targetId, signal } = request;
      const headers = new Headers({ 'Content-Type': 'audio/wav', 'X-LP-Request-Id': requestId });
      const csrf = document.cookie
        .split('; ')
        .find((value) => value.startsWith('lp_csrf='))
        ?.slice(8);
      if (csrf && !isGuest()) headers.set('X-LP-CSRF', decodeURIComponent(csrf));
      const response = await fetch(`${prefix()}/${encodeURIComponent(targetId)}/assess`, {
        method: 'POST',
        body: request.audio,
        headers,
        signal,
        credentials: isGuest() ? 'omit' : 'same-origin',
      });
      if (!response.ok) throw new Error(`PRONUNCIATION_HTTP_${response.status}`);
      const result = (await response.json()) as PronunciationAssessment;
      for (const value of [result.match, result.recognition]) {
        if (
          value.contractVersion !== 1 ||
          value.requestId !== requestId ||
          value.targetId !== targetId ||
          !['none', 'acoustic'].includes(value.evidence) ||
          typeof value.toneAssessed !== 'boolean'
        )
          throw new Error('INVALID_PRONUNCIATION_RESPONSE');
      }
      if (
        !['matched', 'retry', 'uncertain', 'unavailable'].includes(result.match.status) ||
        (['matched', 'retry'].includes(result.match.status) &&
          result.match.evidence !== 'acoustic') ||
        result.match.evidence !== result.recognition.evidence ||
        result.match.toneAssessed !== result.recognition.toneAssessed ||
        !['recognized', 'uncertain', 'unavailable'].includes(result.recognition.status) ||
        (result.recognition.status === 'recognized' &&
          (result.recognition.evidence !== 'acoustic' ||
            typeof result.recognition.recognizedPinyin !== 'string' ||
            !result.recognition.recognizedPinyin.trim())) ||
        typeof result.saved !== 'boolean'
      )
        throw new Error('INVALID_PRONUNCIATION_RESPONSE');
      if (signal?.aborted) throw new DOMException('cancelled', 'AbortError');
      return result;
    })().catch((error: unknown) => {
      if (request.signal?.aborted || (error instanceof Error && error.name === 'AbortError'))
        throw new DOMException('cancelled', 'AbortError');
      const context = {
        contractVersion: 1 as const,
        requestId: request.requestId,
        targetId: request.targetId,
        evidence: 'none' as const,
        toneAssessed: false,
      };
      const invalidAudio = error instanceof Error && /HTTP_(413|415|422)$/.test(error.message);
      const status = invalidAudio ? ('uncertain' as const) : ('unavailable' as const);
      const code = error instanceof Error ? error.message : '';
      const reason = invalidAudio
        ? ('invalid-audio' as const)
        : code.endsWith('HTTP_404')
          ? ('unsupported-target' as const)
          : code.endsWith('HTTP_429')
            ? ('busy' as const)
            : /HTTP_(408|504)$/.test(code)
              ? ('timeout' as const)
              : code.endsWith('HTTP_503')
                ? ('model-unavailable' as const)
                : ('network-error' as const);
      return {
        match: { ...context, status, reason },
        recognition: { ...context, status, reason, recognizedPinyin: null },
        saved: false,
        createdAt: new Date().toISOString(),
      };
    });
    return pending;
  }
  return {
    assess,
    match: async (request) => (await assess(request)).match,
    recognize: async (request) => (await assess(request)).recognition,
  };
}

export async function pronunciationHistory(
  targetId: string,
  signal?: AbortSignal,
): Promise<PronunciationHistory> {
  if (isGuest()) return { items: [], counts: {} };
  const response = await fetch(`${prefix()}/${encodeURIComponent(targetId)}/history`, {
    signal,
    credentials: 'same-origin',
  });
  if (!response.ok) throw new Error('PRONUNCIATION_HISTORY_UNAVAILABLE');
  return response.json() as Promise<PronunciationHistory>;
}
