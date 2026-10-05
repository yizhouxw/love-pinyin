import { readFile, writeFile } from 'node:fs/promises';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { format, resolveConfig } from 'prettier';

// Run before editing/bumping a committed curriculum. Never overwrite a revision.
execFileSync('git', ['diff', '--exit-code', 'HEAD', '--', 'content/curriculum.json']);
const content = JSON.parse(await readFile('content/curriculum.json', 'utf8'));
const indexPath = 'content/history/index.json';
const index = JSON.parse(await readFile(indexPath, 'utf8'));
if (!/^\d{4}\.\d{2}\.\d{2}(?:-draft)?\.\d+$/u.test(content.contentVersion))
  throw new Error('Unsupported content version format');
const file = `${content.contentVersion}.json`;
const formatting = { ...(await resolveConfig('content/history/index.json')), parser: 'json' };
const snapshot = {
  contentVersion: content.contentVersion,
  exercises: content.exercises.map((question) => {
    const q = { ...question };
    delete q.reviewStatus;
    return q;
  }),
};
const text = await format(JSON.stringify(snapshot, null, 2), formatting);
const sha256 = createHash('sha256').update(text).digest('hex');
const existing = index.revisions.find((r) => r.contentVersion === content.contentVersion);
if (existing) {
  if (existing.sha256 !== sha256 || (await readFile(`content/history/${file}`, 'utf8')) !== text)
    throw new Error('An immutable revision already exists with different content');
} else {
  await writeFile(`content/history/${file}`, text);
  index.revisions.push({
    contentVersion: content.contentVersion,
    file,
    sourceCommit: execFileSync('git', ['rev-parse', 'HEAD'], { encoding: 'utf8' }).trim(),
    sha256,
  });
  await writeFile(indexPath, await format(JSON.stringify(index, null, 2), formatting));
}
console.log(`Preserved content revision ${content.contentVersion}`);
