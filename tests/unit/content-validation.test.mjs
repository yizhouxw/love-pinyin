import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { validateCurriculum } from '../../scripts/content-validation.mjs';

const data = JSON.parse(readFileSync('content/curriculum.json', 'utf8'));
const schema = JSON.parse(readFileSync('schemas/curriculum.schema.json', 'utf8'));
const sourceData = JSON.parse(readFileSync('content/sources.json', 'utf8'));
const sourceIds = (Array.isArray(sourceData) ? sourceData : sourceData.sources).map((s) => s.id);
const validate = (input, release = false) =>
  validateCurriculum(input, schema, { sourceIds, release });

describe('课程内容的保护门禁', () => {
  it('当前草稿结构成立，但不冒称可正式发布', () => {
    expect(validate(data)).toEqual([]);
    expect(validate(data, true)).toContain('release: teacher review incomplete');
  });
  it('拒绝坏答案与课程依赖环', () => {
    const bad = structuredClone(data);
    bad.exercises[0].answer.optionId = 'missing';
    bad.lessons[0].prerequisiteLessonIds.push(bad.lessons.at(-1).id);
    const errors = validate(bad).join('\n');
    expect(errors).toContain('answer not in options');
    expect(errors).toContain('prerequisite cycle');
  });
  it('拒绝拼音音频引用丢失或知识项失去题目覆盖', () => {
    const bad = structuredClone(data);
    bad.exercises[0].audioRef = 'unknown';
    bad.knowledgeItems[0].requiredModes.push('blend-choice');
    const errors = validate(bad).join('\n');
    expect(errors).toContain('unknown audio');
    expect(errors).toContain('required mode blend-choice uncovered');
  });
});
