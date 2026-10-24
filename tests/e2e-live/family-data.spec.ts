import { expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { test } from '../support/real-server';

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
  const choice = page.getByRole('group', { name: '选择答案' }).getByRole('button').first();
  await expect(choice).toBeEnabled({ timeout: 15_000 });
  await choice.press('Enter');
  await expect(page.locator('.feedback')).toBeVisible();
  await page.getByRole('button', { name: '退出练习' }).click();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await expect(page.getByText(/· 1 次作答/)).toBeVisible();
  await page.getByText('显示设置', { exact: true }).click();
  const reducedMotion = page.getByRole('checkbox', { name: '减少动态效果' });
  await reducedMotion.click();
  await expect(reducedMotion).toBeChecked();
  const downloadEvent = page.waitForEvent('download');
  await page.getByText('备份与恢复', { exact: true }).click();
  await page.getByRole('button', { name: '导出家庭数据' }).click();
  await expect(
    page.getByText('已生成家庭备份并开始下载，请在浏览器下载中确认文件已保存。', { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel('导出的 JSON 数据')).not.toBeVisible();
  await page.getByText('技术详情：查看 JSON', { exact: true }).click();
  const download = await downloadEvent;
  expect(download.suggestedFilename()).toMatch(/\.json$/);
  const downloadedPath = await download.path();
  expect(downloadedPath).toBeTruthy();
  const exported = page.getByLabel('导出的 JSON 数据');
  await expect(exported).toBeVisible();
  const backup = await exported.inputValue();
  const downloadedBackup = await readFile(downloadedPath!, 'utf8');
  expect(JSON.parse(downloadedBackup)).toEqual(JSON.parse(backup));
  const original = JSON.parse(downloadedBackup);
  expect(original.attempts).toHaveLength(1);
  await reducedMotion.click();
  await expect(reducedMotion).not.toBeChecked();

  const fileInput = page.getByLabel('导入家庭备份文件');
  await fileInput.setInputFiles({
    name: 'broken.json',
    mimeType: 'application/json',
    buffer: Buffer.from('{broken'),
  });
  await expect(page.getByRole('alert')).toBeVisible();
  await expect(page.getByText(/· 1 次作答/)).toBeVisible();

  await page.getByText('删除与重置', { exact: true }).click();
  const remove = page.getByRole('button', { name: '删除记录', exact: true });
  await expect(remove).toBeDisabled();
  await page.getByLabel('确认删除文字').fill('取消');
  await expect(remove).toBeDisabled();
  await page.getByLabel('确认删除文字').fill('删除我的学习记录');
  await remove.click();
  await expect(page.getByText(/· 0 次作答/)).toBeVisible();

  await fileInput.setInputFiles({
    name: 'family.json',
    mimeType: 'application/json',
    buffer: Buffer.from(downloadedBackup),
  });
  await expect(page.getByLabel('备份导入预览')).toContainText('1 条练习');
  const restore = page.getByRole('button', { name: '确认替换家庭数据' });
  await expect(restore).toBeDisabled();
  await page.getByLabel('确认替换家庭学习档案文字').fill('替换家庭学习档案');
  await restore.click();
  await expect(page.getByText('家庭数据已恢复。', { exact: true })).toBeVisible();
  await expect(reducedMotion).toBeChecked();
  await expect(page.getByText(/· 1 次作答/)).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await expect(page.getByText(/· 1 次作答/)).toBeVisible();
  await page.getByText('备份与恢复', { exact: true }).click();
  await page.getByRole('button', { name: '导出家庭数据' }).click();
  await expect(
    page.getByText('已生成家庭备份并开始下载，请在浏览器下载中确认文件已保存。', { exact: true }),
  ).toBeVisible();
  await expect(page.getByLabel('导出的 JSON 数据')).not.toBeVisible();
  await page.getByText('技术详情：查看 JSON', { exact: true }).click();
  await expect(exported).toBeVisible();
  const restored = JSON.parse(await exported.inputValue());
  expect(restored.attempts).toEqual(original.attempts);
  expect(restored.sessions).toEqual(original.sessions);
  expect(errors).toEqual([]);
});
