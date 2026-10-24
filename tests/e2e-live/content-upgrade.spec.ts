import { expect } from '@playwright/test';
import { readFile } from 'node:fs/promises';
import { test } from '../support/real-server';

test('DATA-01: legacy content backup restores through parent UI and continues learning', async ({
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
  const history = JSON.parse(await readFile('content/history/2026.10.05.10.json', 'utf8'));
  const current = JSON.parse(await readFile('content/curriculum.json', 'utf8'));
  for (const instance of original.exerciseInstances)
    expect(history.exercises.find((q: { id: string }) => q.id === instance.exercise_id)).toEqual(
      current.exercises.find((q: { id: string }) => q.id === instance.exercise_id),
    );
  // The first lesson questions are identical in this registered older revision.
  // Retag the actual downloaded file to exercise the old-backup UI contract.
  original.contentVersion = original.profile.contentVersion = '2026.10.05.10';
  for (const row of original.sessions) row.contentVersion = '2026.10.05.10';
  for (const row of original.exerciseInstances) row.content_version = '2026.10.05.10';
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
    buffer: Buffer.from(JSON.stringify(original)),
  });
  await expect(page.getByLabel('备份导入预览')).toContainText('1 条练习');
  await expect(page.getByLabel('备份导入预览')).toContainText('保留当时的题目和成绩');
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
  await page.getByText('技术详情：查看 JSON', { exact: true }).click();
  await expect(exported).toBeVisible();
  const restored = JSON.parse(await exported.inputValue());
  expect(restored.attempts).toEqual(original.attempts);
  expect(restored.sessions).toEqual(original.sessions);
  await page.getByRole('button', { name: '返回学习', exact: true }).click();
  await page.getByRole('button', { name: '开始今天的练习' }).click();
  await expect(page.locator('.play-nav strong')).toHaveText('第 1 / 6 关');
  await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 15000 });
  await page.locator('.game-option').first().press('Enter');
  await expect(page.locator('.feedback')).toBeVisible();
  const after = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
  expect(after.attempts).toHaveLength(2);
  expect(after.sessions).toHaveLength(original.sessions.length + 1);
  expect(after.sessions.find((s: { id: string }) => s.id === original.sessions[0].id)).toEqual(
    original.sessions[0],
  );
  expect(errors).toEqual([]);
});

test('DATA-01: old guest tab upgrades and keeps saved answers after reload', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '开始今天的练习' }).click();
  await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 15000 });
  await page.locator('.game-option').first().press('Enter');
  await expect(page.locator('.feedback')).toBeVisible();
  // Wait for the queued progress read to persist before constructing an old cache.
  await expect(page.getByRole('button', { name: '继续 →', exact: true })).toBeEnabled();
  await page.evaluate(() => {
    const cached = JSON.parse(sessionStorage.getItem('lp.guest.v1')!);
    cached.state.contentVersion = cached.state.profile.contentVersion = '2026.10.05.10';
    for (const row of cached.state.sessions) row.contentVersion = '2026.10.05.10';
    for (const row of cached.state.exerciseInstances) row.content_version = '2026.10.05.10';
    sessionStorage.setItem('lp.guest.v1', JSON.stringify(cached));
  });
  await page.reload();
  await expect(page.locator('.play-nav strong')).toHaveText('第 2 / 6 关');
  if (await page.getByText('听题目说明', { exact: true }).isVisible())
    await page.getByText('听题目说明', { exact: true }).click();
  await page.getByRole('button', { name: '听题目', exact: true }).click();
  await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 15000 });
  await page.locator('.game-option').first().press('Enter');
  await expect(page.locator('.feedback')).toBeVisible();
  const state = await page.evaluate(() => JSON.parse(sessionStorage.getItem('lp.guest.v1')!).state);
  expect(state.attempts).toHaveLength(2);
  expect(state.sessions[0].contentVersion).toBe('2026.10.05.10');
  expect(state.contentVersion).not.toBe('2026.10.05.10');
});
