import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import { pairForHouseholdMaterial } from '../support/household-material';

test('UX-12: contextual settings and help stay near their tasks across pages', async ({
  page,
  appUrl,
}) => {
  await pairForHouseholdMaterial(page, appUrl);
  const capture = async (name: string) => {
    for (const width of [1280, 820, 390]) {
      await page.setViewportSize({ width, height: 1000 });
      await page.evaluate(() => window.scrollTo(0, 0));
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page.screenshot({
        path: test.info().outputPath(`${name}-${width}.png`),
        fullPage: true,
      });
    }
  };
  await capture('home');
  await expect(page.locator('.home-help')).toHaveCount(0);
  await page.getByRole('button', { name: '进入词语天天练 →' }).click();
  await expect(page.locator('.word-options')).toHaveCount(0);
  await expect(page.locator('.word-toolbar summary')).toHaveAccessibleName('播放设置');
  await capture('words');
  await page.getByLabel('玩法与提示', { exact: true }).click();
  await expect(page.locator('.context-help .word-about')).toHaveCount(1);
  await page.getByRole('button', { name: '完成', exact: true }).click();
  await page.getByRole('button', { name: '返回首页' }).click();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await capture('daily');
  await page.getByRole('button', { name: '返回小岛', exact: false }).click();
  await page.getByRole('button', { name: '进入游戏乐园' }).click();
  await expect(page.locator('.game-zone-heading .context-help')).toHaveCount(1);
  await expect(page.locator('.game-home-info')).toHaveCount(0);
  await capture('games');
  await page.getByRole('button', { name: '回到学习', exact: false }).click();
  await page.getByRole('button', { name: '课堂学习', exact: true }).click();
  await capture('lesson');
  await page.getByRole('button', { name: '写一写', exact: true }).click();
  await expect(page.locator('.writing-controls summary')).toHaveAccessibleName('播放设置');
  await capture('writing');
  await page.getByRole('button', { name: '返回学习路线', exact: false }).click();
  await page.getByRole('button', { name: '家长管理', exact: true }).click();
  await page.getByRole('button', { name: '我是家长，继续', exact: true }).click();
  await capture('parent');
});
