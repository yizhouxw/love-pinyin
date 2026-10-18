import { expect } from '@playwright/test';
import { test } from '../support/real-server';

test.use({ selectedPinyinSource: true });

test('DAILY-07: multi-column navigation follows autoplay without moving page or focus', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: '开始第 1 份跟读' }).click();
  await page.getByRole('checkbox', { name: '语音引导', exact: true }).uncheck();
  const list = page.getByLabel('第1份本节内容');
  const first = list.getByRole('button').first();
  const second = list.getByRole('button').nth(1);
  expect((await first.boundingBox())!.y).toBe((await second.boundingBox())!.y);
  expect((await first.boundingBox())!.x).toBeLessThan((await second.boundingBox())!.x);
  // Make a small directory viewport so the real playback must scroll across blocks.
  await list.evaluate((node) => {
    node.style.maxHeight = '150px';
  });
  const play = page.getByRole('button', { name: '连播本节' });
  await play.focus();
  await play.click();
  const guidance = page.getByRole('checkbox', { name: '语音引导', exact: true });
  await guidance.focus();
  const pageTop = await page.evaluate(() => window.scrollY);
  await expect
    .poll(async () => list.evaluate((node) => node.scrollTop), { timeout: 25000 })
    .toBeGreaterThan(0);
  const active = list.locator('[aria-current="step"]');
  await expect(active).toHaveCount(1);
  const bounds = (await list.boundingBox())!;
  const target = (await active.boundingBox())!;
  expect(target.y).toBeGreaterThanOrEqual(bounds.y);
  expect(target.y + target.height).toBeLessThanOrEqual(bounds.y + bounds.height);
  expect(await page.evaluate(() => window.scrollY)).toBe(pageTop);
  await expect(guidance).toBeFocused();
  await page.getByRole('button', { name: '停止示范' }).click();
  const last = list.getByRole('button').last();
  await last.click();
  await expect(last).toHaveAttribute('aria-current', 'step');
  await page.getByRole('button', { name: '← 上一条', exact: true }).click();
  await expect(
    list.getByRole('button').nth((await list.getByRole('button').count()) - 2),
  ).toHaveAttribute('aria-current', 'step');
  await page.getByRole('button', { name: '第 4 份', exact: true }).click();
  await page.getByRole('button', { name: '开始第 4 份跟读' }).click();
  const nextList = page.getByLabel('第4份本节内容');
  await expect(nextList.getByRole('button').first()).toHaveAttribute('aria-current', 'step');
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.screenshot({
    path: `private/daily07-${test.info().project.name}.png`,
    fullPage: true,
  });
});
