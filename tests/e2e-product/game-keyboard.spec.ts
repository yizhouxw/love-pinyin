import { expect } from '@playwright/test';
import { test } from '../support/real-server';
test.use({ selectedPinyinSource: true });
test('KEY-01: two-dimensional boat navigation, pause, native buttons and voice keep keyboard access', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在本机生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭' }).click();
  await page.getByRole('button', { name: '进入游戏乐园' }).click();
  await page.getByRole('button', { name: '开始河湾划船' }).click();
  const stage = page.locator('.adventure-canvas');
  await expect(page.locator('button[data-option-id]').first()).toBeEnabled({ timeout: 20000 });
  await stage.focus();
  await page.keyboard.press('ArrowLeft');
  await expect.poll(async () => Number(await stage.getAttribute('data-world-x'))).toBeLessThan(200);
  await page.keyboard.press('ArrowUp');
  await expect.poll(async () => Number(await stage.getAttribute('data-world-y'))).toBeLessThan(320);
  await page.keyboard.press('p');
  await expect(page.getByRole('button', { name: '▶ 继续游戏', exact: true })).toBeVisible();
  const y = await stage.getAttribute('data-world-y');
  await page.waitForTimeout(250);
  expect(await stage.getAttribute('data-world-y')).toBe(y);
  await page.keyboard.press('p');
  await page.getByRole('button', { name: '玩法与故事', exact: true }).click();
  await page.getByRole('button', { name: '听本关故事', exact: true }).focus();
  await page.keyboard.press('Space');
  await expect(page.getByRole('button', { name: '停止听本关故事', exact: true })).toBeVisible();
  await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click();
  const target = page.locator('button[data-option-id]').first();
  await expect(target).toBeEnabled({ timeout: 20000 });
  await target.focus();
  await page.keyboard.press('Enter');
  await expect
    .poll(async () => await stage.getAttribute('data-world-hit'), { timeout: 15000 })
    .not.toBe('');
});
