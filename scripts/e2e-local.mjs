import { execFileSync, spawnSync } from 'node:child_process';
import { readFileSync } from 'node:fs';

const version = JSON.parse(
  readFileSync('node_modules/@playwright/test/package.json', 'utf8'),
).version;
const macOS =
  process.platform === 'darwin'
    ? execFileSync('sw_vers', ['-productVersion'], { encoding: 'utf8' }).trim()
    : null;
const knownLocalIssue = !process.env.CI && macOS?.startsWith('27.') && version === '1.63.0';
const projects = knownLocalIssue
  ? ['desktop-chromium', 'desktop-webkit', 'tablet-webkit', 'phone-webkit', 'phone-chromium']
  : [];
if (knownLocalIssue) {
  console.warn(
    '本机 macOS 27 + Playwright 1.63 的 Firefox 启动与上游 #42768 问题一致。\n' +
      '本命令只验证 5 个 Chromium/WebKit 项目；Firefox 仍未验证。\n' +
      '完整 6 项目命令 npm run test:e2e 保留，Linux CI 不排除 Firefox。',
  );
}
const result = spawnSync(
  process.execPath,
  [
    'node_modules/@playwright/test/cli.js',
    'test',
    '--config',
    'config/playwright.config.ts',
    ...projects.map((p) => `--project=${p}`),
  ],
  { stdio: 'inherit' },
);
if (result.error) console.error(result.error.message);
process.exitCode = result.status ?? 1;
