import { expect } from '@playwright/test';
import { test } from '../support/real-server';

test('RECOVERY-01: real server restart preserves saved work and replays one pending answer', async ({
  page,
  appUrl,
  serverControl,
}) => {
  const errors: string[] = [];
  const answers: Array<{ path: string; body: unknown }> = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => {
    if (request.method() === 'POST' && /\/instances\/[^/]+\/answer$/u.test(request.url()))
      answers.push({ path: new URL(request.url()).pathname, body: request.postDataJSON() });
  });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭' }).click();
  await page.getByRole('button', { name: '开始今天的练习' }).click();
  const choice = page.getByRole('group', { name: '选择答案' }).getByRole('button').first();
  await expect(choice).toBeEnabled({ timeout: 15_000 });
  await choice.press('Enter');
  await expect(page.locator('.feedback')).toBeVisible();
  expect(answers).toHaveLength(1);
  const firstResponse = await page.request.get(`${appUrl}/api/v1/profiles/export`);
  expect(firstResponse.ok()).toBe(true);
  const saved = await firstResponse.json();
  expect(saved.attempts).toHaveLength(1);
  await page.getByRole('button', { name: '继续 →', exact: true }).click();
  await expect(choice).toBeEnabled({ timeout: 15_000 });
  await serverControl.stop();
  await expect(async () => {
    await fetch(`${appUrl}/api/v1/health`);
  }).rejects.toThrow();
  await choice.press('Enter');
  // A stopped server can fail both narration and the answer request at once.
  await expect(page.getByRole('alert').filter({ hasText: '本次操作尚未确认' })).toBeVisible();
  await expect(page.locator('.feedback')).toHaveCount(0);
  expect(answers).toHaveLength(2);

  await serverControl.start();
  await page.reload();
  await expect.poll(() => answers.length).toBe(3);
  expect(answers[2]).toEqual(answers[1]);
  await expect(page.getByRole('button', { name: '退出练习' })).toBeVisible();
  await page.getByRole('button', { name: '退出练习' }).click();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await page.getByText('备份与恢复', { exact: true }).click();
  await page.getByRole('button', { name: '导出家庭数据' }).click();
  await page.getByText('技术详情：查看 JSON', { exact: true }).click();
  const backup = JSON.parse(await page.getByLabel('导出的 JSON 数据').inputValue());
  expect(backup.attempts).toHaveLength(2);
  expect(backup.attempts.find((row: { id: string }) => row.id === saved.attempts[0].id)).toEqual(
    saved.attempts[0],
  );
  expect(new Set(backup.attempts.map((row: { instance_id: string }) => row.instance_id)).size).toBe(
    2,
  );
  await page.reload();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await page.getByText('备份与恢复', { exact: true }).click();
  await page.getByRole('button', { name: '导出家庭数据' }).click();
  await page.getByText('技术详情：查看 JSON', { exact: true }).click();
  const reloaded = JSON.parse(await page.getByLabel('导出的 JSON 数据').inputValue());
  expect(reloaded.attempts).toEqual(backup.attempts);
  expect(answers).toHaveLength(3);
  expect(errors).toEqual([]);
});
