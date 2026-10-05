import { expect } from '@playwright/test';
import { test } from '../support/review-server';

test('REVIEW-05: actual source playback, frame-cut preview and isolated draft without activation', async ({
  page,
  reviewUrl,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(reviewUrl);
  await expect(page.getByRole('status')).toContainText('1份课程录音');
  await expect(page.locator('#candidate option')).not.toHaveCount(0);
  await page.locator('#target').selectOption('audio-final-a');
  await page.locator('#start').fill('14.2');
  await page.locator('#end').fill('16.2');
  await page.getByRole('button', { name: '从开始位置听原音' }).click();
  await expect
    .poll(() =>
      page.locator('#original').evaluate((element) => (element as HTMLAudioElement).currentTime),
    )
    .toBeGreaterThan(14.2);
  await page.getByRole('button', { name: '试听裁切', exact: true }).click();
  await expect
    .poll(() =>
      page
        .locator('#preview-audio')
        .evaluate((element) => (element as HTMLAudioElement).currentTime),
    )
    .toBeGreaterThan(0.1);
  expect(
    await page.locator('#original').evaluate((element) => (element as HTMLAudioElement).paused),
  ).toBe(true);
  expect(
    await page
      .locator('#preview-audio')
      .evaluate((element) => (element as HTMLAudioElement).duration),
  ).toBeCloseTo(2, 2);
  await page.getByRole('button', { name: '保存草稿' }).click();
  await expect(page.locator('#draft-status')).toContainText('草稿已保存');
  await expect(page.getByRole('button', { name: '启用家庭标准音' })).toBeDisabled();
  await page.reload();
  await expect(page.getByRole('status')).toContainText('0个目标已启用');
  await page.locator('#target').selectOption('audio-final-a');
  await expect(page.locator('#draft-status')).toContainText('已加载保存的草稿');
  await expect(page.locator('#start')).toHaveValue('14.2');
  await page.locator('#end').fill('99999');
  await page.getByRole('button', { name: '试听裁切', exact: true }).click();
  await expect(page.getByRole('status')).toHaveClass('error');
  expect(errors).toEqual([]);
});
