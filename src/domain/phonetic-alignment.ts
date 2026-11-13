import content from '../../content/hanzi-pinyin-alignment.json';
import { pinyinSyllables } from './pinyin-spelling';
export type PhoneticUnit = { hanzi: string; pinyin: string; before: string; after: string };
/** Structural alignment only. Erhua groupings come from reviewed course content. */
export function alignPhonetics(text: string, pinyin: string): PhoneticUnit[] | null {
  const normalized = text.normalize('NFC');
  const chunks = Array.from(normalized.matchAll(/(\p{Script=Han})([^\p{Script=Han}]*)/gu));
  const characters = chunks.map((match) => match[1]!).join('');
  const groups =
    (content.joinedCharacters as Record<string, string[]>)[characters] ?? Array.from(characters);
  const syllables = pinyinSyllables(pinyin.normalize('NFC')).map((s) =>
    s.replace(/[，。！？、；：,.!?;:]/gu, ''),
  );
  if (groups.length !== syllables.length || !chunks.length) return null;
  let cursor = 0;
  return groups.map((hanzi, i) => {
    const start = cursor;
    cursor += Array.from(hanzi).length;
    return {
      hanzi,
      pinyin: syllables[i]!,
      before: start === 0 ? normalized.slice(0, chunks[0]!.index) : '',
      after: chunks[cursor - 1]?.[2] ?? '',
    };
  });
}
