import { describe, expect, it } from 'vitest';
import { pinyinTone, splitPinyinCandidate } from '../../src/domain/pinyin-presentation';

describe('拼音游戏的字形呈现', () => {
  it('使用课程清单中最长的声母切分音节，保留 ü 和调号', () => {
    const initials = ['z', 'zh', 'n', 'g'];
    expect(splitPinyinCandidate('zhǔ', initials)).toEqual({ onset: 'zh', rime: 'ǔ' });
    expect(splitPinyinCandidate('nǚ', initials)).toEqual({ onset: 'n', rime: 'ǚ' });
    expect(splitPinyinCandidate('guā', initials)).toEqual({ onset: 'g', rime: 'uā' });
  });

  it('不拆分无声母音节或说明文字', () => {
    expect(splitPinyinCandidate('yī', ['b', 'w'])).toBeNull();
    expect(splitPinyinCandidate('ü 的两点', ['n'])).toBeNull();
  });

  it('从拼音调号与声调名称得到四声调型编号', () => {
    expect(['ā', 'á', 'ǎ', 'à'].map(pinyinTone)).toEqual([1, 2, 3, 4]);
    expect(pinyinTone('ǚ')).toBe(3);
    expect(pinyinTone('第二声')).toBe(2);
    expect(pinyinTone('u')).toBeNull();
  });
});
