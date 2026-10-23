import { expect } from '@playwright/test';
import { test } from '../support/real-server';

test.use({ selectedPinyinSource: true });

test('READ-08: word and long sentence characters sit below pinyin and wrap on narrow screens', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('checkbox', { name: '语音引导', exact: true }).uncheck();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: '第 7 份', exact: true }).click();
  await page.getByRole('button', { name: /^读词语/ }).click();
  const target = page.locator('.daily-target');
  await expect(target.locator('rt')).toHaveText(['紫', '色']);
  await page.getByRole('button', { name: /^读句子/ }).click();
  await expect(target.locator('rt')).toHaveCount(24);
  for (const width of [1280, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    const layout = await target.evaluate((element) => {
      const pairs = [...element.querySelectorAll('ruby')];
      return {
        overflow: document.documentElement.scrollWidth > innerWidth,
        aligned: pairs.every((pair) => {
          const pinyin = pair.querySelector('span')!.getBoundingClientRect();
          const hanzi = pair.querySelector('rt')!.getBoundingClientRect();
          return hanzi.top >= pinyin.bottom - 1 && hanzi.height < pinyin.height;
        }),
      };
    });
    expect(layout).toEqual({ overflow: false, aligned: true });
    await page.screenshot({ path: `private/read08-${width}.png`, fullPage: true });
  }
});
