import { readFileSync } from 'node:fs';
import { describe, it, expect } from 'vitest';
import { validateIllustrations } from '../../scripts/validate-illustrations.mjs';
import { validateNarration } from '../../scripts/validate-narration.mjs';
const load = (p) => JSON.parse(readFileSync(p, 'utf8'));
const book = load('content/illustrations.json');
const curriculum = load('content/curriculum.json');
const narration = load('content/narration.json');
const svg = (id) => readFileSync(`public/illustrations/${id}.svg`, 'utf8');
const questions = curriculum.exercises.filter(
  (q) => q.pictureId || q.options.some((o) => o.pictureId),
);
describe('WORD-01 picture and meaning contracts', () => {
  it('has six authored pictures per lesson and preserves original question activities', () => {
    expect(validateIllustrations(book, curriculum, narration, svg)).toEqual([]);
    expect(Object.keys(book.items)).toHaveLength(84);
    expect(questions).toHaveLength(24);
    for (const lesson of curriculum.lessons)
      expect(Object.values(book.items).filter((item) => item.lessonId === lesson.id)).toHaveLength(
        6,
      );
    for (const [id, item] of Object.entries(book.items)) {
      if (!id.startsWith('v1-')) continue;
      const pair = questions.filter((q) => q.lessonId === item.lessonId);
      expect(pair).toHaveLength(2);
      expect(pair[0].type).toBe('listen-choice');
      expect(pair[1].pictureId).toBe(id);
      expect(pair[1].type).toBe(
        pair[1].primaryKnowledgeId.startsWith('k-whole-') ? 'symbol-choice' : 'blend-choice',
      );
      expect(pair.every((q) => q.audioRef === item.audioRef)).toBe(true);
    }
  });
  it('rejects wrong sounds, missing pictures, wrong descriptions and future prerequisites', () => {
    const bad = structuredClone(book);
    bad.items['v1-rice'].audioRef = bad.items['v1-cat'].audioRef;
    bad.items['v1-soil'].prerequisiteKnowledgeIds = ['k-final-ing'];
    const errors = validateIllustrations(bad, curriculum, narration, (id) => {
      if (id === 'v1-pig') throw Error();
      return svg(id);
    }).join('\n');
    expect(errors).toContain('standard target');
    expect(errors).toContain('prerequisites');
    expect(errors).toContain('missing SVG');
    const wrong = structuredClone(narration);
    wrong.exercises['q-03-150'].options.a = '另一张图片。';
    expect(validateIllustrations(book, curriculum, wrong, svg).join('\n')).toContain(
      'spoken option',
    );
  });
  it('rejects active or remote SVG content and requires Chinese descriptions for picture options', () => {
    for (const markup of [
      '<script>alert(1)</script>',
      '<image href="https://example.com/x.png"/>',
      '<path onclick="evil()"/>',
      '<path fill="url(https://example.com)"/>',
    ])
      expect(
        validateIllustrations(book, curriculum, narration, (id) =>
          svg(id).replace('</svg>', markup + '</svg>'),
        ).length,
      ).toBeGreaterThan(0);
    const wrong = structuredClone(narration);
    delete wrong.exercises['q-03-150'].options.a;
    expect(validateNarration(curriculum, wrong).join('\n')).toContain('missing Mandarin option');
    expect(validateNarration(curriculum, narration)).toEqual([]);
  });
});
