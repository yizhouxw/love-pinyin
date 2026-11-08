import curriculum from '../../content/curriculum.json';
import spelling from '../../content/pinyin-spelling.json';
import { pinyinTone, splitPinyinCandidate } from './pinyin-presentation';

export type ReadingMode = 'direct' | 'spelling';
export type SpellingClip = { kind: 'audio' | 'daily-audio' | 'voice'; id: string };
const wholeSyllables = new Set(curriculum.inventory.wholeSyllables);
const audioParts = new Map(
  curriculum.audioRequirements
    .filter(({ kind }) => kind === 'initial' || kind === 'final')
    .map(({ kind, transcript, id }) => [`${kind}/${transcript}`, id]),
);
const writtenFinals: Readonly<Record<string, string>> = spelling.writtenWithoutInitial;
const compoundFinals: Readonly<Record<string, string[]>> = spelling.compoundFinals;

function plainSyllable(value: string) {
  return value
    .toLowerCase()
    .normalize('NFD')
    .replace(/[\u0300\u0301\u0304\u030c]/gu, '')
    .normalize('NFC')
    .replaceAll('v', 'ü');
}

export function isWholeSyllable(value: string) {
  return wholeSyllables.has(plainSyllable(value));
}

export function pinyinSyllables(value: string) {
  return value
    .trim()
    .split(/[\s'’·-]+/u)
    .filter(Boolean);
}

export function spellingPlan(
  syllables: string[],
  recorded: readonly string[],
  existing: readonly string[] = [],
) {
  return syllables.flatMap((value, position) => {
    const plain = plainSyllable(value);
    const tone = pinyinTone(value);
    const key = `${plain.replaceAll('ü', 'v')}${tone ?? 5}`;
    const full = existing[position] ?? (recorded.includes(key) ? `spelling-${key}` : null);
    const result: (SpellingClip & { position: number })[] = [];
    if (!wholeSyllables.has(plain)) {
      const parts = splitPinyinCandidate(plain, curriculum.inventory.initials);
      const onset = parts?.onset;
      let rime = parts?.rime ?? writtenFinals[plain] ?? plain;
      if (onset && spelling.umlautInitials.includes(onset)) rime = rime.replace(/^u/u, 'ü');
      const finals = compoundFinals[rime] ?? [rime];
      // A standalone sound already has its full demonstration. Keep a neutral
      // syllable in its word when there is no matching isolated recording.
      if (onset || finals.length > 1) {
        const initialId = onset ? audioParts.get(`initial/${onset}`) : undefined;
        if (initialId) result.push({ kind: 'audio', id: initialId, position });
        for (const final of finals) {
          const id = audioParts.get(`final/${final}`);
          if (id) result.push({ kind: 'audio', id, position });
        }
      }
    }
    if (full) result.push({ kind: 'daily-audio', id: full, position });
    return result;
  });
}
