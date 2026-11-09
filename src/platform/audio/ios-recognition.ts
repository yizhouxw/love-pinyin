import reading from '../../../content/reading-recognition.json';
import { shopRules } from '../../domain/pinyin-shop';
import type { PronunciationService } from '../../domain/pronunciation';
import { iosOperation } from '../ios-app';

type NativeText =
  | { status: 'recognized'; transcript: string; pinyin: string }
  | { status: 'unavailable' | 'uncertain' };

export type IOSModelStatus = { state: string; bytes?: number; received?: number };

export function iosModelStatus(download = false) {
  return iosOperation<IOSModelStatus>(download ? 'modelDownload' : 'modelStatus');
}

export function baseSyllable(value: string) {
  return value
    .toLowerCase()
    .replaceAll('u:', 'ü')
    .replaceAll('v', 'ü')
    .replaceAll('ɑ', 'a')
    .replaceAll('ɡ', 'g')
    .normalize('NFD')
    .replace(/(?!\u0308)\p{M}/gu, '')
    .normalize('NFC')
    .replace(/[1-5]$/, '');
}

export function observedSyllables(value: string): string[] {
  const tokens = value.replace(/u:/gi, 'ü').match(/[\p{L}\p{M}\p{N}]+/gu) ?? [];
  return tokens.every((token) => /^[a-zü]+$/i.test(baseSyllable(token))) ? tokens : [];
}

export function gameSyllable(syllable: string): string {
  const rules = shopRules.readingTolerance;
  const initialAliases: Readonly<Record<string, string>> = rules.isolatedVowels;
  const base = baseSyllable(syllable);
  let result = initialAliases[base] ?? base;
  for (const [plain, retroflex] of rules.initialPairs) {
    if (result.startsWith(retroflex!)) {
      result = plain + result.slice(retroflex!.length);
      break;
    }
  }
  for (const [front, back] of rules.finalPairs) {
    if (result.endsWith(back!)) {
      result = result.slice(0, -back!.length) + front;
      break;
    }
  }
  return result;
}

export function matchesDaily(expected: readonly string[], observed: readonly string[]): boolean {
  const aliases: Readonly<Record<string, readonly string[]>> = reading.initialReadingAliases;
  return (
    expected.length === observed.length &&
    expected.every((syllable, index) => {
      const target = baseSyllable(syllable);
      return (aliases[target] ?? [target]).includes(baseSyllable(observed[index]!));
    })
  );
}

export async function recognizeIOSAudio(audio: Blob, forShop: boolean, signal?: AbortSignal) {
  signal?.throwIfAborted();
  const bytes = new Uint8Array(await audio.arrayBuffer());
  let binary = '';
  for (let i = 0; i < bytes.length; i += 8192) {
    binary += String.fromCharCode(...bytes.subarray(i, i + 8192));
  }
  signal?.throwIfAborted();
  const result = await iosOperation<NativeText>('recognizeAudio', { audio: btoa(binary), forShop });
  signal?.throwIfAborted();
  return result;
}

export function createIOSShopPronunciation(
  targets: readonly { id: string; pinyin: string }[],
): PronunciationService {
  let previous: Parameters<PronunciationService['match']>[0] | undefined;
  let pending: ReturnType<typeof recognizeIOSAudio> | undefined;
  const transcribe = (request: Parameters<PronunciationService['match']>[0]) => {
    if (request === previous && pending) return pending;
    previous = request;
    pending = recognizeIOSAudio(request.audio, true, request.signal);
    return pending;
  };
  function context(request: Parameters<PronunciationService['match']>[0]) {
    return {
      contractVersion: 1 as const,
      requestId: request.requestId,
      targetId: request.targetId,
      toneAssessed: false,
    };
  }
  return {
    async match(request) {
      const target = targets.find((item) => item.id === request.targetId);
      const result = await transcribe(request);
      const pinyin = result.status === 'recognized' ? observedSyllables(result.pinyin) : [];
      if (
        target &&
        pinyin.length === 1 &&
        gameSyllable(target.pinyin) === gameSyllable(pinyin[0]!)
      ) {
        return { ...context(request), evidence: 'acoustic', status: 'matched', reason: null };
      }
      return result.status === 'unavailable'
        ? {
            ...context(request),
            evidence: 'none',
            status: 'unavailable',
            reason: 'model-unavailable',
          }
        : {
            ...context(request),
            evidence: 'none',
            status: 'uncertain',
            reason: 'insufficient-evidence',
          };
    },
    async recognize(request) {
      const result = await transcribe(request);
      if (result.status === 'recognized' && observedSyllables(result.pinyin).length) {
        return {
          ...context(request),
          evidence: 'acoustic',
          status: 'recognized',
          recognizedPinyin: result.pinyin,
          reason: null,
        };
      }
      return result.status === 'unavailable'
        ? {
            ...context(request),
            evidence: 'none',
            status: 'unavailable',
            reason: 'model-unavailable',
            recognizedPinyin: null,
          }
        : {
            ...context(request),
            evidence: 'none',
            status: 'uncertain',
            reason: 'insufficient-evidence',
            recognizedPinyin: null,
          };
    },
  };
}
