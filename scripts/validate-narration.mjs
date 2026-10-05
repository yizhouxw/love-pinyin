import { readFile } from 'node:fs/promises';
import { pathToFileURL } from 'node:url';

const objectiveModes = new Set(['listen-choice', 'symbol-choice', 'tone-choice', 'blend-choice']);
const requiredUi = [
  'welcome',
  'correct',
  'incorrect',
  'hint',
  'summary',
  'rest',
  'next',
  'skip',
  'exit',
  'retry',
  'lesson',
  'start',
  'audio_error',
  'blend_how',
  'blend_ready',
];
const spokenChinese = /^[\p{Script=Han}\s，。！？、；：…“”‘’（）《》「」『』—·]+$/u;
const hasHan = /\p{Script=Han}/u;
const pinyin = /[a-züāáǎàōóǒòēéěèīíǐìūúǔùǖǘǚǜ]+/giu;
const isRecord = (value) => value !== null && typeof value === 'object' && !Array.isArray(value);

/** Validate scripts, not sound quality, teaching correctness, or publication rights. */
export function validateNarration(curriculum, narration) {
  const errors = [];
  if (!isRecord(narration)) return ['narration: expected an object'];
  if (narration.version !== 1) errors.push('narration: unsupported version');

  function checkText(text, location) {
    if (
      typeof text !== 'string' ||
      !hasHan.test(text) ||
      !spokenChinese.test(text) ||
      text.length > 300 ||
      text !== text.normalize('NFC')
    ) {
      errors.push(`${location}: expected NFC Mandarin script without pinyin, digits, or markup`);
    } else if (/占位|待补充|待生成|示例音频/.test(text)) {
      errors.push(`${location}: placeholder script`);
    }
  }

  const ui = isRecord(narration.ui) ? narration.ui : {};
  for (const key of requiredUi) {
    if (!(key in ui)) errors.push(`ui: missing ${key}`);
  }
  for (const [key, value] of Object.entries(ui)) {
    if (!/^[a-z][a-z_]*$/.test(key)) errors.push(`ui: invalid key ${key}`);
    checkText(value?.text, `ui.${key}.text`);
  }

  const scripts = isRecord(narration.exercises) ? narration.exercises : {};
  const exercises = curriculum.exercises.filter((exercise) => objectiveModes.has(exercise.type));
  const byId = new Map(exercises.map((exercise) => [exercise.id, exercise]));
  for (const key of Object.keys(scripts)) {
    if (!byId.has(key)) errors.push(`exercises: unknown or excluded exercise ${key}`);
  }
  for (const exercise of exercises) {
    const script = scripts[exercise.id];
    if (!isRecord(script)) {
      errors.push(`exercises: missing ${exercise.id}`);
      continue;
    }
    checkText(script.text, `${exercise.id}.text`);
    checkText(script.hint, `${exercise.id}.hint`);

    // Moving the original pinyin into a large visual cue must neither lose a
    // target nor introduce the answer of an auditory question into the screen.
    const originalTargets = exercise.prompt.match(pinyin) ?? [];
    const visualTargets =
      typeof script.visualCue === 'string' ? (script.visualCue.match(pinyin) ?? []) : [];
    if (JSON.stringify(originalTargets) !== JSON.stringify(visualTargets)) {
      errors.push(`${exercise.id}.visualCue: pinyin targets must match the original prompt`);
    }
    if (
      script.visualCue !== undefined &&
      (typeof script.visualCue !== 'string' ||
        script.visualCue.length === 0 ||
        script.visualCue.length > 100 ||
        script.visualCue !== script.visualCue.normalize('NFC'))
    ) {
      errors.push(`${exercise.id}.visualCue: expected a nonempty NFC display cue`);
    }
    if (exercise.type === 'listen-choice' && script.visualCue !== undefined) {
      errors.push(`${exercise.id}.visualCue: auditory targets must not be disclosed`);
    }

    if (!isRecord(script.options)) {
      errors.push(`${exercise.id}.options: expected an object`);
      continue;
    }
    const options = new Map(exercise.options.map((option) => [option.id, option]));
    for (const option of exercise.options) {
      if (hasHan.test(option.label) && !(option.id in script.options)) {
        errors.push(`${exercise.id}.options: missing Mandarin option ${option.id}`);
      }
    }
    for (const [optionId, text] of Object.entries(script.options)) {
      const option = options.get(optionId);
      if (!option) errors.push(`${exercise.id}.options: unknown option ${optionId}`);
      else if (!hasHan.test(option.label)) {
        errors.push(`${exercise.id}.options.${optionId}: pinyin targets must not use narration`);
      }
      checkText(text, `${exercise.id}.options.${optionId}`);
    }
  }
  return errors;
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  const [curriculum, narration] = await Promise.all(
    ['content/curriculum.json', 'content/narration.json'].map(async (file) =>
      JSON.parse(await readFile(file, 'utf8')),
    ),
  );
  const errors = validateNarration(curriculum, narration);
  if (errors.length) {
    console.error(errors.join('\n'));
    process.exitCode = 1;
  } else {
    console.log(
      `朗读脚本结构通过：${Object.keys(narration.exercises).length}道客观题 / ${Object.keys(narration.ui).length}条界面引导。此检查不等同语音试听或教师审校。`,
    );
  }
}
