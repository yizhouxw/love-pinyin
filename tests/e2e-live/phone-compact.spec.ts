import { expect, type Locator, type Page } from '@playwright/test';
import { test } from '../support/real-server';
import { pairForHouseholdMaterial } from '../support/household-material';
import games from '../../content/games.json' with { type: 'json' };

test.use({ selectedPinyinSource: true, viewport: { width: 320, height: 568 } });

async function checkFirstScreen(page: Page, controls: Locator[]) {
  await page.evaluate(() => window.scrollTo(0, 0));
  for (const control of controls) {
    await expect(control).toBeInViewport({ ratio: 0.99 });
  }
  expect(await page.evaluate(() => scrollY)).toBe(0);
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(
    await page.evaluate(() => innerWidth),
  );
}

test('PHONE-01: classroom question and response controls fit on a small phone', async ({
  page,
  appUrl,
}) => {
  await pairForHouseholdMaterial(page, appUrl);
  await page.getByRole('button', { name: '课堂学习', exact: true }).click();
  await page.getByRole('button', { name: '练一练', exact: true }).click();
  await page.getByRole('button', { name: '开始本课练习' }).click();
  const controls = [
    page.locator('.question-card h1'),
    page.locator('.listen-question'),
    page.locator('.options'),
    page.locator('.exercise-actions'),
  ];
  await checkFirstScreen(page, controls);
  await page.setViewportSize({ width: 667, height: 375 });
  await checkFirstScreen(page, controls);
});

test('PHONE-02: daily reading and dictation controls stay with their material', async ({
  page,
  appUrl,
}) => {
  await pairForHouseholdMaterial(page, appUrl);
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  const start = page.getByRole('button', { name: '开始第 1 份跟读' });
  await checkFirstScreen(page, [start]);
  await start.click();
  const reading = [
    page.locator('.daily-target'),
    page.locator('.daily-reader-controls > .daily-actions'),
    page.locator('.daily-next'),
  ];
  await checkFirstScreen(page, reading);
  await page.setViewportSize({ width: 667, height: 375 });
  await checkFirstScreen(page, reading);
  await page.getByRole('button', { name: '返回小岛' }).click();
  await page.getByRole('button', { name: '进入词语天天练' }).click();
  await page.getByRole('button', { name: /^选择课程/ }).click();
  await page
    .getByRole('dialog')
    .getByRole('button', { name: '选择口耳目手足', exact: true })
    .click();
  await page.getByRole('button', { name: '词语听写', exact: true }).click();
  const dictation = [page.locator('.word-answer'), page.locator('.word-dictation-controls')];
  await checkFirstScreen(page, dictation);
  await page.setViewportSize({ width: 320, height: 568 });
  await checkFirstScreen(page, dictation);
  await page.getByRole('button', { name: '揭晓答案' }).click();
  await checkFirstScreen(page, dictation);
});

for (const game of games.games) {
  test(`PHONE-03 ${game.scene}: play and hint controls fit across rotation`, async ({
    page,
    appUrl,
  }) => {
    await pairForHouseholdMaterial(page, appUrl);
    await page.getByRole('button', { name: '进入游戏乐园' }).click();
    await page.getByRole('button', { name: `开始${game.title}` }).click();
    const controls = [
      page.locator('.scene-nav'),
      page.locator('.adventure-canvas'),
      page.getByRole('button', { name: '听提示', exact: true }),
    ];
    const action = {
      runner: page.getByRole('button', { name: '跳起来 ↑', exact: true }),
      boat: page.getByRole('button', { name: '停船', exact: true }),
      drum: page.locator('.adventure-canvas button[data-option-id]').first(),
      space: page.getByRole('button', { name: '发射 · 空格', exact: true }),
    }[game.scene as 'runner' | 'boat' | 'drum' | 'space'];
    await checkFirstScreen(page, [...controls, action]);
    await page.setViewportSize({ width: 390, height: 844 });
    await checkFirstScreen(page, [...controls, action]);
    await page.setViewportSize({ width: 667, height: 375 });
    await checkFirstScreen(page, [...controls, action]);
  });
}
