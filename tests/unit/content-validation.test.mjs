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
  it('BANK-02为原先缺题的二十一项提供两道不同视觉复习题，不移除听辨要求', () => {
    const added = data.exercises.filter((q) => {
      const sequence = Number(q.id.split('-').at(-1));
      return sequence >= 30 && sequence < 40;
    });
    const affected = new Set(added.map((q) => q.primaryKnowledgeId));
    expect(affected.size).toBe(21);
    for (const id of affected) {
      const questions = data.exercises.filter(
        (q) => q.primaryKnowledgeId === id && q.type !== 'read-aloud' && !q.audioRef,
      );
      expect(questions.length, id).toBeGreaterThanOrEqual(2);
      expect(new Set(questions.map((q) => q.prompt)).size, id).toBe(questions.length);
    }
    expect(data.coverage.insufficientObjectiveReviewKnowledgeIds).toEqual([]);
    expect(data.knowledgeItems.find((k) => k.id === 'k-final-a').requiredModes).toContain(
      'listen-choice',
    );
    const neutral = added.find((q) => q.primaryKnowledgeId === 'k-tone-0');
    expect(neutral.prompt).toContain('爸爸');
    expect(neutral.options.find((o) => o.id === neutral.answer.optionId).label).toBe('ba');
  });
  it('BANK-03每个知识点至少两道不同可用视觉题，仍保留所有听辨目标', () => {
    for (const knowledge of data.knowledgeItems) {
      const visual = data.exercises.filter(
        (q) => q.primaryKnowledgeId === knowledge.id && q.type !== 'read-aloud' && !q.audioRef,
      );
      expect(visual.length, knowledge.id).toBeGreaterThanOrEqual(2);
      expect(new Set(visual.map((q) => q.prompt)).size, knowledge.id).toBe(visual.length);
    }
    expect(data.exercises.filter((q) => q.type === 'listen-choice')).toHaveLength(61);
    expect(
      data.knowledgeItems.filter((k) => k.requiredModes.includes('listen-choice')),
    ).toHaveLength(61);
    const byKnowledge = (id) =>
      data.exercises.find(
        (q) => q.primaryKnowledgeId === id && Number(q.id.split('-').at(-1)) >= 40,
      );
    for (const [id, expected] of [
      ['k-initial-zh', 'zh'],
      ['k-final-ve', 'üe'],
      ['k-final-in', 'in'],
      ['k-whole-yu', 'yu'],
    ]) {
      const question = byKnowledge(id);
      expect(question.options.find((o) => o.id === question.answer.optionId).label).toBe(expected);
    }
  });

  it('每课至少六道不同视觉练习，保留听辨与知识点门槛', () => {
    for (const lesson of data.lessons) {
      const questions = data.exercises.filter(
        (q) => q.lessonId === lesson.id && q.type !== 'read-aloud' && !q.audioRef,
      );
      expect(questions.length, lesson.id).toBeGreaterThanOrEqual(6);
      expect(new Set(questions.map((q) => q.prompt)).size, lesson.id).toBe(questions.length);
    }
    expect(validate(data, true)).toContain(
      'release: seed bank needs at least 5 distinct objective primary exercises per knowledge item',
    );
  });

  it('新增拼写题保留两点、省略两点及复韵母标调的不同规则', () => {
    const answer = (id) => {
      const q = data.exercises.find((item) => item.id === id);
      return q.options.find((option) => option.id === q.answer.optionId).label;
    };
    expect(answer('q-04-23')).toBe('lǘ');
    expect(answer('q-06-22')).toBe('xǔ');
    expect(answer('q-11-23')).toBe('jiǔ');
    expect(answer('q-12-21')).toBe('lüè');
  });

  it('当前草稿结构成立，但不冒称可正式发布', () => {
    expect(validate(data)).toEqual([]);
    expect(validate(data, true)).toContain('release: teacher review incomplete');
  });
  it('新增或删除题目时不能保留过期的覆盖率摘要', () => {
    const stale = structuredClone(data);
    stale.coverage.exerciseCount -= 1;
    stale.coverage.objectivePrimaryExerciseCounts['k-final-o'] -= 1;
    const errors = validate(stale);
    expect(errors).toContain('coverage: stale exercise count');
    expect(errors).toContain('coverage: stale primary count for k-final-o');
  });
  it('发音评测不是首版发布门禁', () => {
    const errors = validate(data, true).join('\n');
    expect(errors).not.toContain('assessment engine evidence');
    expect(errors).not.toContain('pronunciation capability');
    expect(errors).not.toContain('assessment coverage');
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
  it('拒绝未齐全证据或越出 public/audio 的已批准录音', () => {
    const bad = structuredClone(data);
    Object.assign(bad.audioRequirements[0], {
      status: 'approved',
      reviewStatus: 'approved',
      file: '../private/voice.wav',
      sha256: 'not-a-digest',
    });
    const errors = validate(bad).join('\n');
    expect(errors).toContain('relative public/audio path');
    expect(errors).toContain('invalid audio SHA-256');
    expect(errors).toContain('rights evidence missing');
    expect(errors).toContain('review evidence missing');
  });
  it('接受路径与摘要格式正确、但仍保留权利与审音证据的录音草稿', () => {
    const draft = structuredClone(data);
    Object.assign(draft.audioRequirements[0], {
      status: 'recorded',
      file: 'audio/final-a.wav',
      sha256: 'a'.repeat(64),
    });
    expect(validate(draft)).toEqual([]);
  });
});
