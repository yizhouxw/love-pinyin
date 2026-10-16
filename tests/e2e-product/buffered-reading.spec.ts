import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import { observeReadingMedia, playedReading } from '../support/media-log';

test.use({ selectedPinyinSource: true });

test('DAILY-06: simulated page visibility clears preparation and returning prepares without autoplay', async ({
  page,
  appUrl,
}) => {
  await observeReadingMedia(page);
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: '开始第 1 份跟读' }).click();
  const reader = page.getByLabel('当前跟读内容');
  await reader.getByRole('checkbox', { name: '语音引导', exact: true }).uncheck();
  await expect(page.getByLabel('声音准备')).toContainText('本份声音已就绪');
  await reader.getByRole('button', { name: 'ā', exact: true }).click();
  await expect.poll(() => playedReading(page, 'daily-audio')).toHaveLength(1);
  // Exercise the app lifecycle handler; this is not an iPad background test.
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => true });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(page.getByLabel('声音准备')).toContainText('0 / 0');
  await expect(reader.getByRole('status')).toContainText('点开始跟读');
  await page.evaluate(() => {
    Object.defineProperty(document, 'hidden', { configurable: true, get: () => false });
    document.dispatchEvent(new Event('visibilitychange'));
  });
  await expect(page.getByLabel('声音准备')).toContainText('本份声音已就绪');
  expect(await playedReading(page, 'daily-audio')).toHaveLength(1);
  await reader.getByRole('button', { name: 'ā', exact: true }).click();
  await expect.poll(() => playedReading(page, 'daily-audio')).toHaveLength(2);
  await page.getByRole('button', { name: '返回小岛' }).click();
  await expect(page.getByLabel('声音准备')).toHaveCount(0);
});

test('DAILY-06: fully prepared short clips replay and switch with the audio network blocked', async ({
  page,
  appUrl,
}) => {
  test.setTimeout(60000);
  const requests: string[] = [];
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: '开始第 1 份跟读' }).click();
  const reader = page.getByLabel('当前跟读内容');
  await reader.getByRole('checkbox', { name: '语音引导', exact: true }).uncheck();
  await expect(page.getByLabel('声音准备')).toContainText('本份声音已就绪', { timeout: 30000 });
  const block = async (route: import('@playwright/test').Route) => {
    requests.push(route.request().url());
    await route.abort();
  };
  await page.route('**/api/v1/guest/daily-audio/**', block);
  await page.route('**/api/v1/guest/voice/**', block);
  await reader.getByRole('button', { name: 'ā', exact: true }).click();
  await expect(reader.getByRole('status')).toContainText('轮到你读啦', { timeout: 8000 });
  await reader.getByRole('button', { name: 'ā', exact: true }).click();
  await expect(reader.getByRole('status')).toContainText('轮到你读啦', { timeout: 8000 });
  await page.getByLabel('第1份本节内容').getByRole('button').nth(1).click();
  await expect(reader.getByRole('button', { name: 'á', exact: true })).toBeVisible();
  await expect(reader.getByRole('status')).toContainText('轮到你读啦', { timeout: 8000 });
  expect(requests).toEqual([]);
  await expect(reader.getByRole('alert')).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath('buffered-reading.png'), fullPage: true });
});

test('DAILY-06: interrupted first download retries once and remains playable', async ({
  page,
  appUrl,
}) => {
  test.setTimeout(60000);
  let attempts = 0;
  await page.route('**/api/v1/guest/daily-audio/daily-a1', async (route) => {
    if (++attempts === 1) await route.abort();
    else await route.continue();
  });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: '开始第 1 份跟读' }).click();
  const reader = page.getByLabel('当前跟读内容');
  await reader.getByRole('checkbox', { name: '语音引导', exact: true }).uncheck();
  await expect(page.getByLabel('声音准备')).toContainText('本份声音已就绪', { timeout: 30000 });
  expect(attempts).toBe(2);
  await reader.getByRole('button', { name: 'ā', exact: true }).click();
  await expect(reader.getByRole('status')).toContainText('轮到你读啦', { timeout: 8000 });
  expect(attempts).toBe(2);
});
