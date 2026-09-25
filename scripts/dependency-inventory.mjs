import { readFile, writeFile, mkdir } from 'node:fs/promises';

const lock = JSON.parse(await readFile(new URL('../package-lock.json', import.meta.url), 'utf8'));
const packages = Object.entries(lock.packages)
  .filter(([path]) => path !== '')
  .map(([path, p]) => ({
    path,
    version: p.version,
    license: p.license ?? 'REVIEW_REQUIRED',
    dev: p.dev ?? false,
    optional: p.optional ?? false,
    integrity: p.integrity ?? null,
  }));
await mkdir(new URL('../docs/engineering/', import.meta.url), { recursive: true });
await writeFile(
  new URL('../docs/engineering/dependency-inventory.json', import.meta.url),
  JSON.stringify({ source: 'package-lock.json', packages }, null, 2) + '\n',
);
const unknown = packages.filter((p) => p.license === 'REVIEW_REQUIRED');
console.log(`已记录 ${packages.length} 个锁定依赖；缺少许可证声明 ${unknown.length} 个。`);
if (unknown.length) console.log(unknown.map((p) => p.path).join('\n'));
