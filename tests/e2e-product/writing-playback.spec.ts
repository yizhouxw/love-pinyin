import { expect } from '@playwright/test';
import { test } from '../support/real-server';

test.use({ selectedPinyinSource: true });

test('WRITE-03: automatic strokes, optional cross-target playback and cancellation', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '课堂学习' }).click();
  await page.getByRole('button', { name: '写一写', exact: true }).click();
  await page.getByRole('button', { name: '观察 a 的书写', exact: true }).click();
  await expect(page.locator('.writing-instruction')).toContainText('第 1 / 2 笔', {
    timeout: 20000,
  });
  await expect(page.locator('.writing-instruction')).toContainText('第 2 / 2 笔', {
    timeout: 20000,
  });
  await expect(page.getByRole('button', { name: '▶ 播放笔顺' })).toBeVisible({ timeout: 20000 });
  await expect(page.getByRole('button', { name: '观察 a 的书写', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await page
    .getByRole('region', { name: '书写小课堂' })
    .getByRole('checkbox', { name: '语音引导', exact: true })
    .uncheck();
  await expect(page.getByRole('button', { name: '▶ 播放笔顺' })).toBeVisible();
  await page
    .getByRole('region', { name: '书写小课堂' })
    .getByRole('checkbox', { name: '语音引导', exact: true })
    .check();
  await page.getByRole('checkbox', { name: '连读', exact: true }).click();
  await page.getByRole('button', { name: '▶ 播放笔顺' }).click();
  await expect(page.getByRole('button', { name: '观察 o 的书写', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
    { timeout: 45000 },
  );
  await page.getByRole('button', { name: '■ 停止演示' }).click();
  await page.waitForTimeout(1800);
  await expect(page.getByRole('button', { name: '▶ 播放笔顺' })).toBeVisible();
  await page.getByText('逐笔观察', { exact: true }).click();
  await page.getByRole('button', { name: '看第一笔' }).press('Enter');
  await expect(page.locator('.writing-stage .active')).toHaveCount(1);
  await page.getByRole('button', { name: '观察 e 的书写', exact: true }).click();
  await page.getByRole('button', { name: '听一听', exact: true }).click();
  await page.waitForTimeout(1500);
  await expect(page.locator('.writing-stage')).toHaveCount(0);
});
