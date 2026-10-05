import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { validateNarration } from '../../scripts/validate-narration.mjs';

const curriculum = JSON.parse(readFileSync('content/curriculum.json', 'utf8'));
const narration = JSON.parse(readFileSync('content/narration.json', 'utf8'));

describe('初学儿童的中文朗读脚本', () => {
  it('覆盖全部客观题和汉字选项，将拼音保留为视觉目标', () => {
    expect(validateNarration(curriculum, narration)).toEqual([]);
    expect(Object.keys(narration.exercises)).toHaveLength(117);
    expect(narration.exercises['q-03-05'].visualCue).toBe('b ＋ ā');
    expect(narration.exercises['q-13-10'].options).toEqual({
      a: '有两点的那一组',
      b: '没有两点的那一组',
    });
  });

  it('不允许新题漏配脚本或选项，避免重新出现仅靠认字的题目', () => {
    const bad = structuredClone(narration);
    delete bad.exercises['q-14-08'];
    delete bad.exercises['q-01-08'].options.b;
    delete bad.ui.incorrect;
    const errors = validateNarration(curriculum, bad).join('\n');
    expect(errors).toContain('missing q-14-08');
    expect(errors).toContain('q-01-08.options: missing Mandarin option b');
    expect(errors).toContain('ui: missing incorrect');
  });

  it('拒绝将拼音或混合拼音直接送入普通话合成', () => {
    const bad = structuredClone(narration);
    bad.exercises['q-03-06'].text = 'mǎ 是第几声？';
    bad.exercises['q-01-08'].options.a = 'a 的上方';
    bad.ui.next.text = '进入第 2 题';
    const errors = validateNarration(curriculum, bad).join('\n');
    expect(errors).toContain('q-03-06.text: expected NFC Mandarin');
    expect(errors).toContain('q-01-08.options.a: expected NFC Mandarin');
    expect(errors).toContain('ui.next.text: expected NFC Mandarin');
  });

  it('不能漏掉视觉拼音或泄露听辨目标，也不能把拼音选项替换成合成音', () => {
    const bad = structuredClone(narration);
    delete bad.exercises['q-03-05'].visualCue;
    bad.exercises['q-01-01'].visualCue = 'a';
    bad.exercises['q-01-01'].options.a = '啊';
    bad.exercises['q-01-01'].options.z = '错误选项';
    const errors = validateNarration(curriculum, bad).join('\n');
    expect(errors).toContain('q-03-05.visualCue: pinyin targets must match');
    expect(errors).toContain('q-01-01.visualCue: auditory targets must not be disclosed');
    expect(errors).toContain('q-01-01.options.a: pinyin targets must not use narration');
    expect(errors).toContain('q-01-01.options: unknown option z');
  });

  it('不接受排除的朗读题或占位说明充当真实脚本', () => {
    const bad = structuredClone(narration);
    bad.exercises['q-01-10'] = { text: '这条语音待生成。', options: {} };
    bad.ui.welcome.text = '内容待补充。';
    const errors = validateNarration(curriculum, bad).join('\n');
    expect(errors).toContain('unknown or excluded exercise q-01-10');
    expect(errors).toContain('ui.welcome.text: placeholder script');
  });
});
