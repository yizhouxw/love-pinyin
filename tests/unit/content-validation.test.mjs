import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { validateCurriculum } from '../../scripts/content-validation.mjs';
import { pinyinTone, splitPinyinCandidate } from '../../src/domain/pinyin-presentation';

const data = JSON.parse(readFileSync('content/curriculum.json', 'utf8'));
const schema = JSON.parse(readFileSync('schemas/curriculum.schema.json', 'utf8'));
const sourceData = JSON.parse(readFileSync('content/sources.json', 'utf8'));
const sourceIds = (Array.isArray(sourceData) ? sourceData : sourceData.sources).map((s) => s.id);
const validate = (input, release = false) =>
  validateCurriculum(input, schema, { sourceIds, release });

describe('课程内容的保护门禁', () => {
  it('CURR-02 records primary-text verification and rejects missing or unregistered evidence', () => {
    expect(validate(data, true)).toEqual([]);
    const copy = structuredClone(data);
    copy.edition.latestRevisionPinyinClauses = 'pending-primary-text-verification';
    expect(validate(copy, true)).toContain(
      'release: latest curriculum clauses need primary-text verification',
    );
    copy.edition.latestRevisionPinyinClauses = 'verified';
    for (const source of [undefined, 'unknown-primary-source']) {
      copy.edition.latestRevisionPrimarySourceId = source;
      expect(validate(copy, true)).toContain(
        'release: latest curriculum verification needs a registered primary source reference',
      );
    }
    copy.edition.latestRevisionPrimarySourceId = data.edition.latestRevisionPrimarySourceId;
    copy.sourceIds = copy.sourceIds.filter(
      (id) => id !== copy.edition.latestRevisionPrimarySourceId,
    );
    expect(validate(copy, true)).toContain(
      'release: latest curriculum verification needs a registered primary source reference',
    );
  });

  it('BANK-07将规则应用到具体拼写、同调听辨和独立中文选项', () => {
    const added = data.exercises.filter(
      (q) => Number(q.id.split('-').at(-1)) >= 120 && Number(q.id.split('-').at(-1)) < 140,
    );
    expect(added).toHaveLength(40);
    expect(data.coverage.insufficientObjectiveReleaseKnowledgeIds).toEqual([]);
    const answer = (id) => {
      const q = added.find((q) => q.id === id);
      return q.options.find((o) => o.id === q.answer.optionId).label;
    };
    for (const [id, expected] of [
      ['q-09-125', 'w'],
      ['q-11-120', 'a'],
      ['q-11-121', 'o'],
      ['q-02-120', '去掉小圆点'],
      ['q-02-121', 'ü'],
      ['q-09-126', 'ya'],
      ['q-09-127', 'wa'],
      ['q-09-128', 'yū'],
      ['q-09-129', 'yù'],
      ['q-12-120', 'yue'],
      ['q-10-120', 'dui'],
      ['q-11-122', 'jiu'],
      ['q-11-123', 'shuì'],
      ['q-11-124', 'niú'],
    ])
      expect(answer(id), id).toBe(expected);
    expect(added.find((q) => q.id === 'q-09-125').prompt).toContain('把 u 写成');
    const order = (id) => data.lessons.find((l) => l.id === id).order;
    for (const q of added) {
      const k = data.knowledgeItems.find((k) => k.id === q.primaryKnowledgeId);
      expect(order(k.lessonId)).toBeLessThanOrEqual(order(q.lessonId));
      if (k.id === 'k-tone-0') expect(pinyinTone(answer(q.id))).toBeNull();
      if (q.type === 'blend-choice')
        expect(answer(q.id)).toBe(q.prompt.match(/[a-züāáǎàōóǒòēéěèīíǐìūúǔùǖǘǚǜ]+/gu).join(''));
      for (const o of q.options)
        if (/\p{Script=Han}/u.test(o.label)) expect(o.audioRef).toBeTruthy();
    }
    const auditory = added.filter((q) => q.audioRef);
    expect(auditory).toHaveLength(9);
    for (const q of auditory) {
      expect(new Set(q.options.map((o) => pinyinTone(o.label))).size).toBe(1);
      expect(data.audioRequirements.find((a) => a.id === q.audioRef).transcript).toBe(answer(q.id));
    }
    const untone = (text) =>
      text
        .normalize('NFD')
        .replace(/[\u0300\u0301\u0304\u030c]/gu, '')
        .normalize('NFC');
    for (const q of auditory)
      for (const option of q.options) {
        const parts = splitPinyinCandidate(option.label, data.inventory.initials) ?? {
          onset: '',
          rime: option.label,
        };
        const final = data.knowledgeItems.find(
          (k) => k.category === 'final' && k.symbol === untone(parts.rime),
        );
        expect(final, q.id).toBeDefined();
        expect(order(final.lessonId)).toBeLessThanOrEqual(order(q.lessonId));
        if (parts.onset) {
          const initial = data.knowledgeItems.find(
            (k) => k.category === 'initial' && k.symbol === parts.onset,
          );
          expect(order(initial.lessonId)).toBeLessThanOrEqual(order(q.lessonId));
        }
      }
    expect(added.find((q) => q.id === 'q-12-121').options.map((o) => o.label)).toEqual([
      'é',
      'ér',
      'hé',
    ]);
    const oldNasal = data.exercises.find((q) => q.id === 'q-14-30');
    expect(oldNasal.options.find((o) => o.id === oldNasal.answer.optionId).label).toBe('en / eng');
  });

  it('BANK-06的整体认读音节在已学范围用同调候选辨听，不靠换顺序凑题', () => {
    const added = data.exercises.filter(
      (q) => Number(q.id.split('-').at(-1)) >= 100 && Number(q.id.split('-').at(-1)) < 120,
    );
    expect(added).toHaveLength(32);
    const untone = (text) =>
      text
        .normalize('NFD')
        .replace(/[\u0300\u0301\u0304\u030c]/gu, '')
        .normalize('NFC');
    const order = (id) => data.lessons.find((l) => l.id === id).order;
    for (const k of data.knowledgeItems.filter((k) => k.category === 'whole-syllable')) {
      const pair = added.filter((q) => q.primaryKnowledgeId === k.id);
      expect(pair, k.id).toHaveLength(2);
      expect(data.coverage.objectivePrimaryExerciseCounts[k.id]).toBeGreaterThanOrEqual(5);
      expect(
        new Set(
          pair.map(
            (q) =>
              q.audioRef +
              q.options
                .map((o) => o.label)
                .sort()
                .join(','),
          ),
        ).size,
      ).toBe(2);
      const tones = [];
      for (const q of pair) {
        expect(q.type).toBe('listen-choice');
        expect(q.knowledgeIds).toEqual([k.id]);
        const answer = q.options.find((o) => o.id === q.answer.optionId).label;
        expect(untone(answer)).toBe(k.symbol);
        expect(data.audioRequirements.find((a) => a.id === q.audioRef).transcript).toBe(answer);
        tones.push(pinyinTone(answer));
        expect(new Set(q.options.map((o) => pinyinTone(o.label)))).toEqual(
          new Set([pinyinTone(answer)]),
        );
        for (const option of q.options) {
          const whole = data.knowledgeItems.find(
            (w) => w.category === 'whole-syllable' && w.symbol === untone(option.label),
          );
          if (whole) {
            expect(order(whole.lessonId)).toBeLessThanOrEqual(order(q.lessonId));
            continue;
          }
          const parts = splitPinyinCandidate(option.label, data.inventory.initials);
          expect(parts, q.id).toBeTruthy();
          const onset = data.knowledgeItems.find(
            (w) => w.category === 'initial' && w.symbol === parts.onset,
          );
          const writtenFinal = untone(parts.rime);
          const finalSymbol =
            ['j', 'q', 'x'].includes(parts.onset) && writtenFinal === 'ue' ? 'üe' : writtenFinal;
          const final = data.knowledgeItems.find(
            (w) => w.category === 'final' && w.symbol === finalSymbol,
          );
          expect(onset, q.id).toBeDefined();
          expect(final, q.id).toBeDefined();
          expect(order(onset.lessonId)).toBeLessThanOrEqual(order(q.lessonId));
          expect(order(final.lessonId)).toBeLessThanOrEqual(order(q.lessonId));
        }
      }
      expect(new Set(tones).size).toBe(k.symbol === 'ri' ? 1 : 2);
      if (k.symbol === 'ri') expect(tones).toEqual([4, 4]);
    }
  });

  it('BANK-05的韵母听辨保持同声母同声调，正确处理ü和ün的拼写及先修范围', () => {
    const added = data.exercises.filter(
      (q) => Number(q.id.split('-').at(-1)) >= 80 && Number(q.id.split('-').at(-1)) < 100,
    );
    expect(added).toHaveLength(48);
    const order = (id) => data.lessons.find((lesson) => lesson.id === id).order;
    const untone = (text) =>
      text
        .normalize('NFD')
        .replace(/[\u0300\u0301\u0304\u030c]/gu, '')
        .normalize('NFC');
    const split = (label) => {
      const part = splitPinyinCandidate(label, data.inventory.initials) ?? {
        onset: '',
        rime: label,
      };
      let final = untone(part.rime);
      if (['j', 'q', 'x'].includes(part.onset) && ['u', 'un'].includes(final))
        final = final.replace('u', 'ü');
      return { onset: part.onset, final };
    };
    for (const knowledge of data.knowledgeItems.filter((k) => k.category === 'final')) {
      const pair = added.filter((q) => q.primaryKnowledgeId === knowledge.id);
      expect(pair, knowledge.id).toHaveLength(2);
      expect(data.coverage.objectivePrimaryExerciseCounts[knowledge.id]).toBeGreaterThanOrEqual(5);
      const conditions = [];
      for (const q of pair) {
        expect(q.type).toBe('listen-choice');
        const candidates = q.options.map((o) => split(o.label));
        expect(new Set(candidates.map((part) => part.onset)).size).toBe(1);
        expect(new Set(q.options.map((o) => pinyinTone(o.label))).size).toBe(1);
        expect(q.options.every((o) => pinyinTone(o.label) !== null)).toBe(true);
        const answer = q.options.findIndex((o) => o.id === q.answer.optionId);
        expect(candidates[answer].final).toBe(knowledge.symbol);
        expect(data.audioRequirements.find((a) => a.id === q.audioRef).transcript).toBe(
          q.options[answer].label,
        );
        for (const part of candidates) {
          const final = data.knowledgeItems.find(
            (k) => k.category === 'final' && k.symbol === part.final,
          );
          expect(final, q.id).toBeDefined();
          expect(order(final.lessonId)).toBeLessThanOrEqual(order(q.lessonId));
          if (part.onset) {
            const onset = data.knowledgeItems.find(
              (k) => k.category === 'initial' && k.symbol === part.onset,
            );
            expect(order(onset.lessonId)).toBeLessThanOrEqual(order(q.lessonId));
          }
        }
        conditions.push(candidates[answer].onset || pinyinTone(q.options[answer].label));
      }
      expect(new Set(conditions).size).toBe(2);
      expect(new Set(pair.map((q) => q.audioRef)).size).toBe(2);
    }
  });
  it('BANK-04每个声母有两种韵母的听辨，干扰项只改变已经学过的声母', () => {
    const added = data.exercises.filter(
      (q) => Number(q.id.split('-').at(-1)) >= 70 && Number(q.id.split('-').at(-1)) < 80,
    );
    expect(added).toHaveLength(42);
    const initials = data.knowledgeItems.filter((k) => k.category === 'initial');
    const lessonOrder = (id) => data.lessons.find((lesson) => lesson.id === id).order;
    for (const knowledge of initials) {
      const pair = added.filter((q) => q.primaryKnowledgeId === knowledge.id);
      expect(pair, knowledge.id).toHaveLength(2);
      expect(data.coverage.objectivePrimaryExerciseCounts[knowledge.id]).toBeGreaterThanOrEqual(5);
      const finals = [];
      for (const q of pair) {
        expect(q.type).toBe('listen-choice');
        const candidates = q.options.map((o) =>
          splitPinyinCandidate(o.label, data.inventory.initials),
        );
        expect(candidates.every(Boolean)).toBe(true);
        expect(new Set(candidates.map((candidate) => candidate.rime)).size).toBe(1);
        const answer = q.options.findIndex((o) => o.id === q.answer.optionId);
        expect(candidates[answer].onset).toBe(knowledge.symbol);
        expect(data.audioRequirements.find((a) => a.id === q.audioRef).transcript).toBe(
          q.options[answer].label,
        );
        for (const candidate of candidates) {
          const onset = initials.find((k) => k.symbol === candidate.onset);
          expect(lessonOrder(onset.lessonId)).toBeLessThanOrEqual(lessonOrder(q.lessonId));
        }
        for (const id of q.knowledgeIds)
          expect(
            lessonOrder(data.knowledgeItems.find((k) => k.id === id).lessonId),
          ).toBeLessThanOrEqual(lessonOrder(q.lessonId));
        finals.push(
          candidates[0].rime
            .normalize('NFD')
            .replace(/[\u0300\u0301\u0304\u030c]/gu, '')
            .normalize('NFC'),
        );
        if (['j', 'q', 'x'].includes(knowledge.symbol) && finals.at(-1) === 'u')
          expect(q.knowledgeIds).toContain('k-final-v');
      }
      expect(new Set(finals).size).toBe(2);
      expect(new Set(pair.map((q) => q.audioRef)).size).toBe(2);
    }
    const wrong = structuredClone(data);
    wrong.exercises.find((q) => q.id === added[0].id).audioRef = added[2].audioRef;
    expect(validate(wrong)).toContain(
      `${added[0].id}: listening answer must match the recorded target`,
    );
  });
  it('TONE-01按真实标准音辨别同一韵母的四声，全部来自已学第一课', () => {
    const auditory = data.exercises.filter((q) => q.type === 'tone-choice' && q.audioRef);
    expect(auditory).toHaveLength(12);
    for (const [base, labels] of [
      ['a', 'āáǎà'],
      ['o', 'ōóǒò'],
      ['e', 'ēéěè'],
    ]) {
      for (const [index, label] of [...labels].entries()) {
        const matches = auditory.filter(
          (q) =>
            q.primaryKnowledgeId === `k-tone-${index + 1}` &&
            q.knowledgeIds.includes(`k-final-${base}`),
        );
        expect(matches).toHaveLength(1);
        const q = matches[0];
        expect(q.lessonId).toBe('lesson-01');
        expect(new Set(q.options.map((o) => o.label))).toEqual(new Set(labels));
        expect(q.options.find((o) => o.id === q.answer.optionId).label).toBe(label);
        expect(data.audioRequirements.find((a) => a.id === q.audioRef).transcript).toBe(label);
        expect(q.prompt).not.toMatch(/[一二三四]声|[a-zāáǎàōóǒòēéěè]/u);
        expect(data.lessons[0].exerciseIds).toContain(q.id);
      }
    }
    expect(validate(data, true)).not.toContain(
      'release: auditory coverage for all four tones missing',
    );
    const stale = structuredClone(data);
    stale.coverage.toneListeningExerciseCount = 0;
    expect(validate(stale)).toContain('coverage: stale tone listening count');
  });
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
    expect(
      data.exercises.filter(
        (q) => q.type === 'listen-choice' && Number(q.id.split('-').at(-1)) < 70,
      ),
    ).toHaveLength(61);
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
    expect(validate(data, true)).not.toContain(
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

  it('当前内容依据与覆盖通过，且不要求教师或音频审批', () => {
    expect(validate(data, true)).toEqual([]);
    expect(validate(data)).toEqual([]);
    expect(validate(data, true).join(' ')).not.toMatch(/teacher|review evidence/);
    expect(validate(data, true)).not.toContain(
      'release: seed bank needs at least 5 distinct objective primary exercises per knowledge item',
    );
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
  it('不再接受音频审批字段作为当前内容格式', () => {
    const bad = structuredClone(data);
    bad.audioRequirements[0].reviewStatus = 'approved';
    expect(validate(bad).join(' ')).toContain('additional properties');
  });
});
