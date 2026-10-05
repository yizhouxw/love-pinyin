import { readFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { validateCurriculum } from './content-validation.mjs';

const readJson = async (path) => JSON.parse(await readFile(path, 'utf8'));
const data = await readJson('content/curriculum.json');
const schema = await readJson('schemas/curriculum.schema.json');
const sources = await readJson('content/sources.json');
const release = process.argv.includes('--release');
const sourceRows = Array.isArray(sources) ? sources : sources.sources;
const errors = validateCurriculum(data, schema, {
  sourceIds: sourceRows.map((s) => s.id),
  release,
});
if (release) {
  try {
    execFileSync('uv', ['run', '--locked', 'python', '-m', 'scripts.validate_audio_resources'], {
      encoding: 'utf8',
    });
  } catch (error) {
    errors.push(`release: ${error.stdout?.trim() || 'local audio resources unavailable'}`);
  }
}
if (errors.length) {
  console.error(errors.join('\n'));
  process.exitCode = 1;
} else {
  console.log(
    `内容${release ? '发布' : '结构'}验证通过：${data.lessons.length}课 / ${data.knowledgeItems.length}知识项 / ${data.exercises.length}题 / ${data.readingTargets.length}朗读目标。`,
  );
  if (!release) console.log('结构验证不替代题量、内容依据与实际声音检查。首版不含发音评测。');
}
