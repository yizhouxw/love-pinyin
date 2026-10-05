import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';

const chinese = /^[\p{Script=Han}\s，。！？、；：…“”‘’（）《》「」『』—·]+$/u;
const safePath = /^M[\d\s.,MLCQ-]+$/;
export function validateWriting(writing, curriculum) {
  const errors = [];
  const reject = (condition, message) => {
    if (!condition) errors.push(message);
  };
  reject(writing.version === 1, 'writing version');
  reject(
    JSON.stringify(writing.grid?.lines) === '[20,80,140,200]' && writing.grid.letterWidth === 150,
    'writing grid',
  );
  const glyphs = writing.glyphs ?? {};
  const lessons = new Map(curriculum.lessons.map((l) => [l.id, l]));
  const expected = new Set(
    [
      ...curriculum.inventory.initials,
      ...curriculum.inventory.finals,
      ...curriculum.inventory.orthographicLetters,
    ].join(''),
  );
  const actual = new Set(Object.values(glyphs).map((g) => g.symbol));
  reject(
    [...expected].every((c) => actual.has(c)) && actual.size === expected.size,
    'writing alphabet coverage',
  );
  const text = (s, location) =>
    reject(
      typeof s === 'string' && chinese.test(s) && s.length <= 300,
      `writing Mandarin: ${location}`,
    );
  for (const key of ['intro', 'paper', 'full', 'choose', 'tones', 'plain'])
    text(writing.ui?.[key], key);
  const marks = writing.marks ?? {};
  reject(
    Object.keys(marks).length === 4 &&
      new Set(Object.values(marks).map((m) => m.combining)).size === 4,
    'writing four tone marks',
  );
  for (const [id, mark] of Object.entries(marks)) {
    reject(
      /^v[0-9]+-[a-z]+$/.test(id) &&
        ['\u0304', '\u0301', '\u030c', '\u0300'].includes(mark.combining),
      `writing tone identity: ${id}`,
    );
  }
  // Tone symbols share the same safe stroke format as the letter trajectories.
  const drawable = {
    ...glyphs,
    ...Object.fromEntries(
      Object.entries(marks).map(([id, mark]) => [
        id,
        {
          symbol: mark.combining,
          lessonId: 'lesson-01',
          sourcePage: 21,
          description: mark.stroke.instruction,
          strokes: [mark.stroke],
        },
      ]),
    ),
  };
  for (const [id, g] of Object.entries(drawable)) {
    reject(
      /^v[0-9]+-[a-z]+$/.test(id) && g.symbol === g.symbol.normalize('NFC'),
      `writing identity: ${id}`,
    );
    reject(lessons.has(g.lessonId), `writing lesson: ${id}`);
    reject(writing.source.pages.includes(g.sourcePage), `writing source: ${id}`);
    text(g.description, id);
    reject(
      Array.isArray(g.strokes) && g.strokes.length > 0 && g.strokes.length <= 4,
      `writing stroke count: ${id}`,
    );
    for (const [i, s] of g.strokes.entries()) {
      const loc = `${id}/${i}`;
      reject(safePath.test(s.d) && safePath.test(s.guide), `writing path: ${loc}`);
      const coordinates = (s.d + ' ' + s.guide).match(/-?\d+(?:\.\d+)?/g)?.map(Number) ?? [];
      reject(
        coordinates.every((n) => n >= 0 && n <= 220),
        `writing bounds: ${loc}`,
      );
      reject(
        Array.isArray(s.start) && s.start.length === 2 && s.start.every((n) => Number.isFinite(n)),
        `writing start: ${loc}`,
      );
      const beginning = s.d.match(/^M\s*(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)/);
      reject(
        beginning && +beginning[1] === s.start[0] && +beginning[2] === s.start[1],
        `writing start mismatch: ${loc}`,
      );
      text(s.instruction, loc);
    }
  }
  const targetIds = new Set();
  for (const lesson of curriculum.lessons) {
    const targets = writing.lessons?.[lesson.id] ?? [];
    reject(targets.length > 0, `writing missing lesson: ${lesson.id}`);
    for (const t of targets) {
      reject(!targetIds.has(t.id), `writing duplicate target: ${t.id}`);
      targetIds.add(t.id);
      const chars = t.glyphIds.map((id) => glyphs[id]?.symbol);
      if (t.tone) {
        const tone = t.tone;
        const mark = marks[tone.markId];
        const letter = chars[tone.glyphIndex];
        reject(
          Number.isInteger(tone.glyphIndex) && 'aoeiuü'.includes(letter ?? '?') && Boolean(mark),
          `writing tone placement: ${t.id}`,
        );
        reject(
          JSON.stringify(tone.omitStrokeIndices) === (letter === 'i' ? '[1]' : '[]'),
          `writing tone dots: ${t.id}`,
        );
        reject(tone.offsetY === (letter === 'ü' ? -14 : 0), `writing tone height: ${t.id}`);
        text(t.note, `${t.id} tone note`);
        if (mark && letter) chars[tone.glyphIndex] = (letter + mark.combining).normalize('NFC');
        if (lesson.order > 2)
          reject(
            curriculum.exercises.some(
              (q) =>
                q.lessonId === lesson.id &&
                q.options.find((o) => o.id === q.answer?.optionId)?.label === t.label,
            ),
            `writing tone curriculum answer: ${t.id}`,
          );
      }
      reject(
        chars.join('') === t.label && t.label === t.label.normalize('NFC'),
        `writing target sequence: ${t.id}`,
      );
      reject(
        t.glyphIds.every(
          (id) => glyphs[id] && lessons.get(glyphs[id].lessonId)?.order <= lesson.order,
        ),
        `writing prerequisite: ${t.id}`,
      );
    }
  }
  for (const q of curriculum.exercises) {
    for (const option of q.options)
      if (option.writing) {
        const glyph = glyphs[option.writing.glyphId];
        text(option.writing.description, `${q.id} option description`);
        reject(q.type === 'symbol-choice', `writing option mode: ${q.id}`);
        reject(Boolean(glyph) && glyph.symbol === option.label, `writing option glyph: ${q.id}`);
        reject(
          lessons.get(glyph?.lessonId)?.order <= lessons.get(q.lessonId)?.order,
          `writing option prerequisite: ${q.id}`,
        );
        reject([-60, 0, 60].includes(option.writing.offsetY), `writing offset: ${q.id}`);
      }
  }
  return errors;
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const errors = validateWriting(
    JSON.parse(readFileSync('content/writing.json', 'utf8')),
    JSON.parse(readFileSync('content/curriculum.json', 'utf8')),
  );
  if (errors.length) {
    console.error(errors.join('\n'));
    process.exitCode = 1;
  } else console.log('书写轨迹、中文步骤、字形引用与课程先修结构通过；内容形状另经目视核对。');
}
