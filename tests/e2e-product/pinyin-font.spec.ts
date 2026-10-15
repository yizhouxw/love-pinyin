import { createHash } from 'node:crypto';
import { expect } from '@playwright/test';
import font from '../../content/pinyin-font.json' with { type: 'json' };
import { test } from '../support/real-server';

test('FONT-01: pinned local fonts load for course and daily pinyin without changing text', async ({
  page,
  appUrl,
}) => {
  const external: string[] = [];
  page.on('request', (request) => {
    if (new URL(request.url()).origin !== appUrl) external.push(request.url());
  });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await expect(page.locator('.lesson-tile').first()).toContainText('a o e');
  for (const asset of font.files) {
    const response = await page.request.get(`${appUrl}/${asset.file.replace(/^public\//, '')}`);
    expect(response.ok()).toBe(true);
    const bytes = await response.body();
    expect(createHash('sha256').update(bytes).digest('hex')).toBe(asset.sha256);
    if (asset.file.endsWith('.woff2')) expect(bytes.subarray(0, 4).toString()).toBe('wOF2');
  }
  const loaded = await page.evaluate(async () => {
    const sample = 'a ā á ǎ à g ü ǖ ǘ ǚ ǜ';
    const regular = await document.fonts.load('400 48px "Andika Pinyin"', sample);
    const bold = await document.fonts.load('700 48px "Andika Pinyin"', sample);
    return {
      regular: regular.map((face) => face.status),
      bold: bold.map((face) => face.status),
      family: getComputedStyle(document.querySelector('.lesson-tile strong')!).fontFamily,
    };
  });
  expect(loaded.regular).toEqual(['loaded']);
  expect(loaded.bold).toEqual(['loaded']);
  expect(loaded.family).toContain('Andika Pinyin');
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: '开始第 1 份跟读', exact: true }).click();
  const target = page.locator('.daily-target');
  await expect(target).toHaveAttribute('aria-label', 'ā');
  await expect(target).toHaveCSS('font-family', /Andika Pinyin/);
  await expect(target).toContainText('ā');
  await page.setViewportSize({ width: 320, height: 800 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(320);
  expect(external).toEqual([]);
  await page.screenshot({ path: test.info().outputPath('pinyin-font.png'), fullPage: true });
});
