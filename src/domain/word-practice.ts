import content from '../../content/word-practice/lessons.json';

export const wordPractice = content;
export type WordLesson = (typeof content.lessons)[number];
export type WordMode = 'read' | 'write' | 'recite';

/** Prefer complete source words, then individual new characters. */
export function highlightWords(text: string, words: string[], characters: string) {
  const candidates = [...new Set(words)].filter(Boolean).sort((a, b) => b.length - a.length);
  const result: { text: string; kind: 'word' | 'character' | 'plain' }[] = [];
  for (let offset = 0; offset < text.length;) {
    const word = candidates.find((value) => text.startsWith(value, offset));
    const value = word ?? text[offset]!;
    result.push({
      text: value,
      kind: word ? 'word' : characters.includes(value) ? 'character' : 'plain',
    });
    offset += value.length;
  }
  return result;
}

export function practiceKey(lessonId: string, mode: WordMode) {
  return `${lessonId}:${mode}`;
}
