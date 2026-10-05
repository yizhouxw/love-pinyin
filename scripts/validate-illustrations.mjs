import { readFileSync } from 'node:fs';
import { pathToFileURL } from 'node:url';
const chinese = /^[\p{Script=Han}\s，。！？、；：…“”‘’（）《》「」『』—·]+$/u;
const idPattern = /^v[0-9]+-[a-z]+$/;
export function validateIllustrations(book, curriculum, narration, readSvg) {
  const errors = [];
  const check = (ok, message) => {
    if (!ok) errors.push(message);
  };
  check(book.version === 1 && book.license === 'MIT', 'pictures version and license');
  check(chinese.test(book.intro) && chinese.test(book.error), 'pictures Mandarin intro and error');
  const items = book.items ?? {};
  const lessons = new Map(curriculum.lessons.map((l) => [l.id, l]));
  const audio = new Map(curriculum.audioRequirements.map((a) => [a.id, a]));
  const knowledge = new Map(curriculum.knowledgeItems.map((k) => [k.id, k]));
  for (const [id, item] of Object.entries(items)) {
    check(idPattern.test(id), `pictures identity: ${id}`);
    check(chinese.test(item.description) && chinese.test(item.name), `pictures Mandarin: ${id}`);
    check(item.pinyin === item.pinyin.normalize('NFC'), `pictures NFC: ${id}`);
    check(lessons.has(item.lessonId), `pictures lesson: ${id}`);
    check(
      audio.get(item.audioRef)?.kind === 'syllable' &&
        audio.get(item.audioRef)?.transcript === item.pinyin,
      `pictures standard target: ${id}`,
    );
    check(
      item.prerequisiteKnowledgeIds?.length > 0 &&
        item.prerequisiteKnowledgeIds.every(
          (k) =>
            knowledge.has(k) &&
            lessons.get(knowledge.get(k).lessonId)?.order <= lessons.get(item.lessonId)?.order,
        ),
      `pictures prerequisites: ${id}`,
    );
    if (idPattern.test(id)) {
      try {
        const svg = readSvg(id);
        check(svg.includes('viewBox="0 0 240 180"'), `pictures viewBox: ${id}`);
        check(
          !/(?:href|\bon[a-z]+\s*=|url\s*\(|<!DOCTYPE|<!ENTITY)/i.test(svg),
          `pictures unsafe SVG: ${id}`,
        );
        const tags = [...svg.matchAll(/<\/?([a-z][a-z0-9:-]*)\b/gi)].map((m) => m[1]);
        check(
          tags.length > 1 &&
            tags.every((tag) =>
              [
                'svg',
                'path',
                'ellipse',
                'circle',
                'rect',
                'line',
                'polygon',
                'polyline',
                'g',
                'title',
              ].includes(tag),
            ),
          `pictures SVG elements: ${id}`,
        );
      } catch {
        errors.push(`pictures missing SVG: ${id}`);
      }
    }
  }
  for (const q of curriculum.exercises) {
    const pictures = q.options.filter((o) => o.pictureId);
    if (!q.pictureId && !pictures.length) continue;
    const correct = q.options.find((o) => o.id === q.answer.optionId);
    const target = items[q.pictureId ?? correct?.pictureId];
    check(
      Boolean(target) &&
        target.pinyin === correct?.label &&
        target.audioRef === q.audioRef &&
        target.lessonId === q.lessonId,
      `pictures question target: ${q.id}`,
    );
    check(
      pictures.length === 0 ||
        (pictures.length === q.options.length && q.type === 'listen-choice' && !q.pictureId),
      `pictures question mode: ${q.id}`,
    );
    if (q.pictureId) {
      check(['blend-choice', 'symbol-choice'].includes(q.type), `pictures prompt mode: ${q.id}`);
      const taught = new Set(
        curriculum.knowledgeItems
          .filter((k) => lessons.get(k.lessonId)?.order <= lessons.get(q.lessonId)?.order)
          .map((k) => k.symbol)
          .join(''),
      );
      for (const o of q.options) {
        const letters = o.label
          .normalize('NFD')
          .replace(/[\u0300\u0301\u0304\u030c]/gu, '')
          .normalize('NFC');
        check(
          [...letters].every((c) => taught.has(c)),
          `pictures candidate prerequisites: ${q.id}`,
        );
      }
    }
    for (const o of pictures) {
      const item = items[o.pictureId];
      check(Boolean(item) && item.pinyin === o.label, `pictures option identity: ${q.id}/${o.id}`);
      check(
        !o.writing &&
          audio.get(o.audioRef)?.kind === 'instruction' &&
          audio.get(o.audioRef)?.transcript === item?.description &&
          narration.exercises[q.id]?.options[o.id] === item?.description,
        `pictures spoken option: ${q.id}/${o.id}`,
      );
    }
  }
  return errors;
}
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const load = (p) => JSON.parse(readFileSync(p, 'utf8'));
  const errors = validateIllustrations(
    load('content/illustrations.json'),
    load('content/curriculum.json'),
    load('content/narration.json'),
    (id) => readFileSync(`public/illustrations/${id}.svg`, 'utf8'),
  );
  if (errors.length) {
    console.error(errors.join('\n'));
    process.exitCode = 1;
  } else console.log('生活图片、标准音、题目与中文说明引用检查通过；图义另作界面目视核对。');
}
