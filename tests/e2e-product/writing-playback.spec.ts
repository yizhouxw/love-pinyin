import { expect } from '@playwright/test';
import { test } from '../support/real-server';

test.use({ selectedPinyinSource: true });

test('WRITE-03: automatic strokes, optional cross-target playback and cancellation', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '听本课录音' }).click();
  await page.getByRole('button', { name: '打开书写课堂' }).click();
  await expect(page.locator('.writing-instruction')).toContainText('第 1 / 2 笔');
  await expect(page.locator('.writing-instruction')).toContainText('第 2 / 2 笔', {
    timeout: 20000,
  });
  await expect(page.getByRole('button', { name: '▶ 重播笔顺' })).toBeVisible({ timeout: 20000 });
  await expect(page.getByRole('button', { name: '观察 a 的书写', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await page.getByRole('button', { name: '连读：关' }).click();
  await page.getByRole('button', { name: '▶ 重播笔顺' }).click();
  await expect(page.getByRole('button', { name: '观察 o 的书写', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
    { timeout: 30000 },
  );
  await page.getByRole('button', { name: '■ 停止演示' }).click();
  await page.waitForTimeout(1800);
  await expect(page.getByRole('button', { name: '▶ 重播笔顺' })).toBeVisible();
  await page.getByText('逐笔观察', { exact: true }).click();
  await page.getByRole('button', { name: '看第一笔' }).press('Enter');
  await expect(page.locator('.writing-stage .active')).toHaveCount(1);
  await page.getByRole('button', { name: '观察 e 的书写', exact: true }).click();
  await page.getByRole('button', { name: '收起书写' }).click();
  await page.waitForTimeout(1500);
  await expect(page.locator('.writing-stage')).toHaveCount(0);
});
