import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import { clearReadingMedia, observeReadingMedia, playedReading } from '../support/media-log';

test.use({ selectedPinyinSource: true });

test('DAILY-12: section-only deduplication and unmarked first tones reach actual playback', async ({
  page,
  appUrl,
}) => {
  await observeReadingMedia(page);
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('checkbox', { name: '语音引导', exact: true }).uncheck();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: '开始第 1 份跟读', exact: true }).click();
  await expect(page.getByLabel('第1份本节内容').getByRole('button')).toHaveCount(12);
  const current = page.getByLabel('当前跟读内容', { exact: true });
  await page.getByRole('button', { name: '换练习', exact: true }).click();
  await page.getByRole('button', { name: '第 4 份', exact: true }).click();
  await page.getByRole('button', { name: /^读一读/ }).click();
  const list = page.getByLabel('第4份本节内容');
  for (const [index, display, audio] of [
    [1, 'de', 'daily-de1'],
    [9, 'ne', 'daily-ne1'],
    [11, 'nu', 'daily-nu1'],
    [12, 'nü', 'daily-nv1'],
    [14, 'le', 'daily-le1'],
    [17, 'lü', 'daily-lv1'],
  ] as const) {
    await clearReadingMedia(page);
    await list.getByRole('button').nth(index).click();
    await expect(current.getByLabel(display, { exact: true })).toBeVisible();
    await expect.poll(() => playedReading(page, 'daily-audio')).toEqual([audio]);
    await expect(current.getByRole('status')).toHaveText('轮到你读啦，读完点下一条。');
    if (index === 11) {
      await expect(current).toContainText('拼音派生示范 · 一声');
      await page.screenshot({
        path: test.info().outputPath('derived-first-tone.png'),
        fullPage: true,
      });
    }
  }
  await page.getByRole('button', { name: '换练习', exact: true }).click();
  await page.getByRole('button', { name: '第 8 份', exact: true }).click();
  await page.getByRole('button', { name: '开始第 8 份跟读', exact: true }).click();
  const navigation = page.getByRole('navigation', { name: '本份小节', exact: true });
  for (const index of [0, 2]) {
    await navigation.locator('.daily-section-tabs button').nth(index).click();
    await expect(
      page.getByLabel('第8份本节内容').getByRole('button').filter({ hasText: /zhi/ }),
    ).toHaveCount(1);
  }
});
