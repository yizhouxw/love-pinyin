import { readFile } from 'node:fs/promises';
import { createHash } from 'node:crypto';
import { resolve, sep } from 'node:path';
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
  const root = resolve('public/audio') + sep;
  for (const asset of data.audioRequirements.filter((a) => a.file)) {
    const path = resolve('public', asset.file.replace(/^\//, ''));
    if (!path.startsWith(root)) {
      errors.push(`audio path outside public/audio: ${asset.id}`);
      continue;
    }
    try {
      const digest = createHash('sha256')
        .update(await readFile(path))
        .digest('hex');
      if (digest !== asset.sha256) errors.push(`audio hash mismatch: ${asset.id}`);
    } catch {
      errors.push(`audio file missing: ${asset.id}`);
    }
  }
}
if (errors.length) {
  console.error(errors.join('\n'));
  process.exitCode = 1;
} else {
  console.log(
    `内容${release ? '发布' : '结构'}验证通过：${data.lessons.length}课 / ${data.knowledgeItems.length}知识项 / ${data.exercises.length}题 / ${data.readingTargets.length}朗读目标。`,
  );
  if (!release)
    console.log('草稿可供开发；教师审校、音频制作与题库扩展尚未通过发布门禁。首版不含发音评测。');
}
