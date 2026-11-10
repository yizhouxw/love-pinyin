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
  return syllables.flatMap<SpellingClip & { position: number }>((value, position) => {
    const plain = plainSyllable(value);
    const bareKey = plain.replaceAll('ü', 'v');
    const exact = existing[position];
    // The legacy practice bank explicitly gives some unmarked entries a first-tone clip.
    const tone = pinyinTone(value) ?? (exact === `daily-${bareKey}1` ? 1 : null);
    const key = `${bareKey}${tone ?? 5}`;
    const fullId = exact ?? (recorded.includes(key) ? `spelling-${key}` : null);
    if (!fullId) return [];
    const full: SpellingClip & { position: number } = { kind: 'daily-audio', id: fullId, position };
    if (!tone || wholeSyllables.has(plain)) return [full];

    const parts = splitPinyinCandidate(plain, curriculum.inventory.initials);
    const onset = parts?.onset;
    let rime = parts?.rime ?? writtenFinals[plain] ?? plain;
    if (onset && spelling.umlautInitials.includes(onset)) rime = rime.replace(/^u/u, 'ü');
    const [medial, final = rime] = compoundFinals[rime] ?? [];
    if (!onset && !medial) return [full];
    const finalKey = `final-${final.replaceAll('ü', 'v')}${tone}`;
    if (!recorded.includes(finalKey)) return [full];

    const result: (SpellingClip & { position: number })[] = [];
    if (onset) {
      const id = audioParts.get(`initial/${onset}`);
      if (!id) return [full];
      result.push({ kind: 'audio', id, position });
    }
    if (medial) {
      const id = audioParts.get(`final/${medial}`);
      if (!id) return [full];
      result.push({ kind: 'audio', id, position });
    }
    return [...result, { kind: 'daily-audio', id: `spelling-${finalKey}`, position }, full];
  });
}
