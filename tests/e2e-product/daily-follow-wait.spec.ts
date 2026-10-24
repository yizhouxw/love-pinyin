import { expect } from '@playwright/test';
import { test } from '../support/real-server';

test.use({ selectedPinyinSource: true });

test('DAILY-08: follow bar counts down and stops with playback', async ({ page, appUrl }) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: '第 1 份', exact: true }).click();
  await page.locator('.daily-sections button').first().click();
  const guidance = page.getByRole('checkbox', { name: '语音引导' });
  if (await guidance.isChecked()) await guidance.uncheck();
  await expect(page.getByText(/源 PDF|原稿：/)).toHaveCount(0);
  await page.getByRole('button', { name: /连播本节/ }).click();
  const bar = page.getByRole('progressbar', { name: '跟读剩余时间' });
  await expect(bar).toBeVisible({ timeout: 20000 });
  await page.screenshot({ path: test.info().outputPath('follow-wait.png') });
  const before = Number(await bar.getAttribute('value'));
  await page.waitForTimeout(200);
  expect(Number(await bar.getAttribute('value'))).toBeLessThan(before);
  await page.getByRole('button', { name: /停止/ }).first().click();
  await expect(bar).toHaveCount(0);
  await page.setViewportSize({ width: 320, height: 740 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
