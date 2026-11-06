import { describe, expect, it } from 'vitest';
import { highlightWords, practiceKey, wordPractice } from '../../src/domain/word-practice';

describe('source-backed word practice', () => {
  it('keeps all 38 lessons and source tasks, without inventing dictation', () => {
    expect(wordPractice.lessons).toHaveLength(38);
    expect(new Set(wordPractice.lessons.map((lesson) => lesson.id)).size).toBe(38);
    expect(wordPractice.lessons.find((lesson) => lesson.title === '天地人')!.write).toEqual([]);
    expect(
      wordPractice.lessons
        .find((lesson) => lesson.title === '日月山川')!
        .read.map((word) => word.text),
    ).toContain('火山');
    expect(
      wordPractice.lessons.find((lesson) => lesson.title === '小小的船')!.characters,
    ).toContain('船');
    expect(wordPractice.lessons.find((lesson) => lesson.title === '影子')!.characters).toContain(
      '影',
    );
    for (const lesson of wordPractice.lessons) {
      expect(lesson.read.length).toBeGreaterThan(0);
      if (lesson.reciteRequirement || lesson.reading.length)
        expect(lesson.passages.length).toBeGreaterThan(0);
      for (const word of [...lesson.read, ...lesson.write]) {
        expect(word.pinyin).toBe(word.pinyin.normalize('NFC'));
        expect(word.text).not.toMatch(/\s/);
      }
    }
  });
  it('highlights longest whole words and remaining new characters without losing punctuation', () => {
    const result = highlightWords('小小的船，船头。', ['小', '小小', '船头'], '的船');
    expect(result.map((part) => part.text).join('')).toBe('小小的船，船头。');
    expect(result[0]).toEqual({ text: '小小', kind: 'word' });
    expect(result[1]).toEqual({ text: '的', kind: 'character' });
    expect(result.find((part) => part.text === '船头')?.kind).toBe('word');
  });
  it('separates modes and lessons for self-confirmed practice', () => {
    expect(practiceKey('word-01', 'read')).not.toBe(practiceKey('word-01', 'write'));
    expect(practiceKey('word-01', 'read')).not.toBe(practiceKey('word-02', 'read'));
  });
});
