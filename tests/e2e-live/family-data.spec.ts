import { spawn } from 'node:child_process';
import { mkdtemp, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { expect, test as base } from '@playwright/test';

// One isolated real server/database per test; browser actions create all data.
const test = base.extend<{ appUrl: string }>({
  // Playwright requires a destructured fixture parameter even without dependencies.
  // eslint-disable-next-line no-empty-pattern
  appUrl: async ({}, use) => {
    const directory = await mkdtemp(join(tmpdir(), 'love-pinyin-live-'));
    const child = spawn(
      'uv',
      ['run', '--locked', 'uvicorn', 'server.main:app', '--host', '127.0.0.1', '--port', '0'],
      {
        env: { ...process.env, LOVE_PINYIN_DATA_DIR: directory },
        stdio: ['ignore', 'pipe', 'pipe'],
      },
    );
    const stopped = new Promise<void>((resolve) => child.once('close', () => resolve()));
    let output = '';
    try {
      const url = await new Promise<string>((resolve, reject) => {
        const timer = setTimeout(
          () => reject(new Error(`Server startup timed out: ${output}`)),
          20_000,
        );
        const collect = (chunk: Buffer) => {
          output += chunk.toString();
          const address = output.match(/Uvicorn running on (http:\/\/127\.0\.0\.1:\d+)/)?.[1];
          if (address) {
            clearTimeout(timer);
            resolve(address);
          }
        };
        child.stdout.on('data', collect);
        child.stderr.on('data', collect);
        child.once('error', (error) => {
          clearTimeout(timer);
          reject(error);
        });
        child.once('close', () => {
          clearTimeout(timer);
          reject(new Error(`Server exited: ${output}`));
        });
      });
      await use(url);
    } finally {
      child.kill('SIGTERM');
      const killTimer = setTimeout(() => child.kill('SIGKILL'), 5_000);
      await stopped;
      clearTimeout(killTimer);
      await rm(directory, { recursive: true });
    }
  },
});

test('R-012-GUI-01: real family backup, deletion and restoration through desktop UI', async ({
  page,
  appUrl,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  const code = (await page.locator('.pair-code').innerText()).match(/[A-Z2-9]{8}/)?.[0];
  expect(code).toBeTruthy();
  await page.getByLabel('家长配对码').fill(code!);
  await page.getByRole('button', { name: '连接家庭' }).click();
  await page.getByRole('button', { name: '开始今天的练习' }).click();
  await page.getByRole('group', { name: '选择答案' }).getByRole('button').first().press('Enter');
  await expect(page.locator('.feedback')).toBeVisible();
  await page.getByRole('button', { name: '退出练习' }).click();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await expect(page.getByText(/· 1 次练习记录/)).toBeVisible();
  await page.getByRole('button', { name: '导出家庭数据' }).click();
  const exported = page.getByLabel('导出的 JSON 数据');
  await expect(exported).toBeVisible();
  const backup = await exported.inputValue();
  const original = JSON.parse(backup);
  expect(original.attempts).toHaveLength(1);

  const fileInput = page.getByLabel('导入家庭备份文件');
  await fileInput.setInputFiles({
    name: 'broken.json',
    mimeType: 'application/json',
    buffer: Buffer.from('{broken'),
  });
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByText(/· 1 次练习记录/)).toBeVisible();

  const remove = page.getByRole('button', { name: '删除记录', exact: true });
  await expect(remove).toBeDisabled();
  await page.getByLabel('确认删除文字').fill('取消');
  await expect(remove).toBeDisabled();
  await page.getByLabel('确认删除文字').fill('删除我的学习记录');
  await remove.click();
  await expect(page.getByText(/· 0 次练习记录/)).toBeVisible();

  await fileInput.setInputFiles({
    name: 'family.json',
    mimeType: 'application/json',
    buffer: Buffer.from(backup),
  });
  await expect(page.getByLabel('备份导入预览')).toContainText('1 条练习');
  const restore = page.getByRole('button', { name: '确认替换家庭数据' });
  await expect(restore).toBeDisabled();
  await page.getByLabel('确认替换家庭学习档案文字').fill('替换家庭学习档案');
  await restore.click();
  await expect(page.getByText('家庭数据已恢复。', { exact: true })).toBeVisible();
  await expect(page.getByText(/· 1 次练习记录/)).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await expect(page.getByText(/· 1 次练习记录/)).toBeVisible();
  await page.getByRole('button', { name: '导出家庭数据' }).click();
  await expect(exported).toBeVisible();
  const restored = JSON.parse(await exported.inputValue());
  expect(restored.attempts).toEqual(original.attempts);
  expect(restored.sessions).toEqual(original.sessions);
  expect(errors).toEqual([]);
});
