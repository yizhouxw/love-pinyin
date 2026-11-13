import examples from '../../content/daily-word-examples.json';
import { describe, expect, it } from 'vitest';
import { alignPhonetics } from '../../src/domain/phonetic-alignment';
import words from '../../content/word-practice/lessons.json';
import daily from '../../content/daily-reading.json';
import hanzi from '../../content/daily-reading-hanzi.json';
describe('phonetic columns', () => {
  it('aligns every supplied reading and dictation word without guessing syllables', () => {
    for (const lesson of words.lessons)
      for (const word of [...lesson.read, ...lesson.write]) {
        const units = alignPhonetics(word.text, word.pinyin);
        expect(units, word.text).not.toBeNull();
        expect(units!.map((u) => u.hanzi).join('')).toBe(word.text);
      }
  });
  it('keeps neutral tones, NFC and explicitly authored erhua groups', () => {
    expect(alignPhonetics('一会儿', 'yi\u0304 huìr')?.map((u) => [u.hanzi, u.pinyin])).toEqual([
      ['一', 'yī'],
      ['会儿', 'huìr'],
    ]);
    expect(alignPhonetics('鱼儿', 'yúr')?.map((u) => u.hanzi)).toEqual(['鱼儿']);
    expect(alignPhonetics('他的', 'tā de')?.[1]?.pinyin).toBe('de');
  });
  it('punctuation stays outside the centered character and unmatched content is explicit', () => {
    expect(alignPhonetics('“你好！”', 'nǐ hǎo')).toEqual([
      { hanzi: '你', pinyin: 'nǐ', before: '“', after: '' },
      { hanzi: '好', pinyin: 'hǎo', before: '', after: '！”' },
    ]);
    expect(alignPhonetics('天空', 'tiān')).toBeNull();
  });
  it('aligns every authored example', () => {
    for (const item of Object.values(examples.items))
      for (const example of item.examples)
        expect(alignPhonetics(example.text, example.pinyin), example.text).not.toBeNull();
  });
  it('aligns all annotated daily items and examples including long sentences', () => {
    for (const day of daily.days)
      for (const section of day.sections)
        for (const item of section.items) {
          const text =
            ('hanzi' in item ? item.hanzi : undefined) ??
            (hanzi as Record<string, string>)[item.id];
          if (typeof text === 'string')
            expect(alignPhonetics(text, item.syllables.join(' ')), item.id).not.toBeNull();
        }
  });
});
