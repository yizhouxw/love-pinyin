import { expect } from '@playwright/test';
import { test } from '../support/real-server';

test('UX-02: course activities are focused, pictures browse individually and practice is directly reachable', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '课堂学习', exact: true }).click();
  await expect(page.locator('.word-card')).toHaveCount(1);
  await expect(page.locator('.writing-stage')).toHaveCount(0);
  await expect(page.locator('.knowledge-card').first()).not.toBeVisible();
  await expect(page.getByRole('button', { name: '← 上一张', exact: true })).toBeDisabled();
  const first = await page.locator('.word-card img').getAttribute('src');
  await page.getByRole('button', { name: '下一张 →', exact: true }).press('Enter');
  await expect(page.locator('.word-card')).toHaveCount(1);
  await expect(page.locator('.word-card img')).not.toHaveAttribute('src', first!);
  await page.getByRole('button', { name: '← 上一张', exact: true }).click();
  await expect(page.locator('.word-card img')).toHaveAttribute('src', first!);
  await page.getByRole('button', { name: '写一写', exact: true }).press('Enter');
  await expect(page.locator('.writing-stage')).toBeVisible();
  await expect(page.locator('.word-card')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '听当前步骤', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '练一练', exact: true }).press('Enter');
  await expect(page.locator('.writing-stage')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '开始本课练习 →', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '开始本课练习 →', exact: true }).press('Enter');
  await expect(page.locator('.play-page')).toBeVisible();
});
