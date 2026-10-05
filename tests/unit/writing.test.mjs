import { readFileSync } from 'node:fs';
import { describe, expect, it } from 'vitest';
import { validateWriting } from '../../scripts/validate-writing.mjs';
import { writingSteps } from '../../src/domain/writing';
import { validateCurriculum } from '../../scripts/content-validation.mjs';
const load = (p) => JSON.parse(readFileSync(p, 'utf8'));
const writing = load('content/writing.json');
const curriculum = load('content/curriculum.json');

describe('WRITE-01 authored handwriting', () => {
  it('covers 26 basic glyphs, authored stroke counts and 14 lesson paths', () => {
    expect(validateWriting(writing, curriculum)).toEqual([]);
    const counts = {
      a: 2,
      o: 1,
      e: 1,
      i: 2,
      u: 2,
      v: 4,
      b: 2,
      p: 2,
      m: 3,
      f: 2,
      d: 2,
      t: 2,
      n: 2,
      l: 1,
      g: 2,
      k: 2,
      h: 2,
      j: 2,
      q: 2,
      x: 2,
      z: 1,
      c: 1,
      s: 1,
      r: 2,
      y: 2,
      w: 2,
    };
    expect(Object.keys(writing.glyphs)).toHaveLength(26);
    for (const [key, count] of Object.entries(counts))
      expect(writing.glyphs[`v1-${key}`].strokes).toHaveLength(count);
    expect(writing.glyphs['v1-j'].placement).toBe('上中下格');
    expect(writing.glyphs['v1-g'].placement).toBe('中下格');
    expect(writing.glyphs['v1-v'].symbol).toBe('ü');
    const target = writing.lessons['lesson-13'].find((t) => t.label === 'yuan');
    const steps = writingSteps(target, writing);
    expect(steps).toHaveLength(8);
    expect(steps[0].glyphId).toBe('v1-y');
    expect(steps[7].glyphId).toBe('v1-n');
  });
  it('rejects incorrect target composition, missing voice scripts and unsafe geometry', () => {
    const bad = structuredClone(writing);
    bad.lessons['lesson-01'][0].glyphIds = ['v1-j'];
    bad.glyphs['v1-a'].strokes[0].d = '<image href="https://example.com">';
    bad.glyphs['v1-v'].strokes[0].instruction = 'write ü';
    bad.glyphs['v1-e'].strokes[0].start = [0, 0];
    const errors = validateWriting(bad, curriculum).join('\n');
    for (const expected of [
      'prerequisite',
      'target sequence',
      'path',
      'Mandarin',
      'start mismatch',
    ])
      expect(errors).toContain(expected);
  });
  it('three diagram tasks distinguish placement, not repeated text labels', () => {
    const questions = curriculum.exercises.filter((q) => q.options.some((o) => o.writing));
    expect(questions).toHaveLength(3);
    for (const q of questions) {
      expect(q.primaryKnowledgeId).toBe('rule-grid-writing');
      expect(q.options.find((o) => o.id === q.answer.optionId).writing.offsetY).toBe(0);
      expect(new Set(q.options.map((o) => o.writing.offsetY))).toEqual(new Set([-60, 0, 60]));
    }
    const bad = structuredClone(curriculum);
    const q = bad.exercises.find((q) => q.id === questions[0].id);
    q.options[1].writing = structuredClone(q.options[0].writing);
    const errors = validateCurriculum(bad, load('schemas/curriculum.schema.json'), {
      sourceIds: load('content/sources.json').sources.map((s) => s.id),
    });
    expect(errors.join('\n')).toContain('duplicate option labels');
  });
});
