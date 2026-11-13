import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import { pairForHouseholdMaterial, useHouseholdMaterial } from '../support/household-material';
test.use({ selectedPinyinSource: true });
test('WORD-16: long word list keeps illustration and selected card together across rotation', async ({
  page,
  appUrl,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await pairForHouseholdMaterial(page, appUrl);
  await useHouseholdMaterial(page);
  await page.getByRole('button', { name: '进入词语天天练 →' }).click();
  const pane = page.getByRole('region', { name: '本课词语' });
  await expect(pane).toBeVisible();
  const cards = pane.getByRole('button');
  await cards.last().click();
  const selected = pane.locator('[aria-pressed="true"]');
  await expect(selected).toBeInViewport();
  await expect(page.locator('.word-selected-picture')).toBeInViewport();
  const before = await page.evaluate(() => scrollY);
  await page.getByRole('button', { name: '连读本课', exact: true }).click();
  await expect(cards.first()).toHaveAttribute('aria-pressed', 'true');
  await expect(cards.first()).toBeInViewport();
  expect(await page.evaluate(() => scrollY)).toBe(before);
  await expect(cards.last()).toHaveAttribute('aria-pressed', 'true', { timeout: 80000 });
  await expect(cards.last()).toBeInViewport();
  await expect(page.locator('.word-selected-picture')).toBeInViewport();
  expect(await page.evaluate(() => scrollY)).toBe(before);
  await page.setViewportSize({ width: 844, height: 390 });
  await expect(selected).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: '停止播放', exact: true }).click();
  await page.screenshot({
    path: test.info().outputPath('reading-workspace-landscape.png'),
    fullPage: true,
  });
});

test('WORD-17: each syllable stays centered over its character in cards, pictures and dictation', async ({
  page,
  appUrl,
}) => {
  await pairForHouseholdMaterial(page, appUrl);
  await useHouseholdMaterial(page);
  await page.getByRole('button', { name: '进入词语天天练 →' }).click();
  const assertAligned = async (selector: string) => {
    const columns = page.locator(selector).locator('.hanzi-pinyin > ruby');
    expect(await columns.count()).toBeGreaterThan(1);
    const geometry = await columns.evaluateAll((nodes) =>
      nodes.map((node) => {
        const character = node.querySelector('.phonetic-character')!.getBoundingClientRect();
        const pinyin = node.querySelector('rt')!.getBoundingClientRect();
        return {
          offset: Math.abs(character.x + character.width / 2 - pinyin.x - pinyin.width / 2),
          above: pinyin.bottom <= character.top + 1,
        };
      }),
    );
    expect(
      geometry.every((g) => g.offset <= 1 && g.above),
      JSON.stringify(geometry),
    ).toBe(true);
  };
  await assertAligned('.word-selected-picture');
  await assertAligned('.word-grid');
  await page.getByRole('button', { name: /^选择课程/ }).click();
  await page
    .getByRole('dialog')
    .getByRole('button', { name: '选择口耳目手足', exact: true })
    .click();
  await page.getByRole('button', { name: '词语听写', exact: true }).click();
  for (let i = 0; i < 3; i++) {
    await page.getByRole('button', { name: '揭晓答案', exact: true }).click();
    await assertAligned('.word-answer');
    if (i < 2) await page.getByRole('button', { name: '下一个', exact: true }).click();
  }
  for (const [width, height] of [
    [390, 844],
    [844, 390],
    [1180, 820],
    [320, 568],
  ] as const) {
    await page.setViewportSize({ width, height });
    await assertAligned('.word-answer');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({
      path: test.info().outputPath(`dictation-aligned-${width}.png`),
      fullPage: true,
    });
  }
  await page.evaluate(() => (document.documentElement.style.fontSize = '200%'));
  await assertAligned('.word-answer');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
