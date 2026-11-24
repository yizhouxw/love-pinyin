import { selectDailyMaterial } from '../support/daily-material';
import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import { pairForHouseholdMaterial, useHouseholdMaterial } from '../support/household-material';
import original from '../../content/ios-original-practice.json' with { type: 'json' };
import household from '../../content/daily-reading.json' with { type: 'json' };

test.use({ selectedPinyinSource: true });
for (const material of ['original', 'household'] as const) {
  test(`DAILY-16: ${material} directory covers every section and supports selection`, async ({
    page,
    appUrl,
  }) => {
    await pairForHouseholdMaterial(page, appUrl);
    if (material === 'household') await useHouseholdMaterial(page);
    await page.getByRole('button', { name: '进入天天练拼音' }).click();
    for (let day = 0; day < 14; day++) {
      if (day > 0) await selectDailyMaterial(page, day + 1);
      await page.getByRole('button', { name: `开始第 ${day + 1} 份跟读` }).click();
      const sections =
        material === 'original'
          ? original.daily[day]!
          : household.days[day]!.sections.map((section) => section.items);
      for (let section = 0; section < sections.length; section++) {
        const list = page.getByLabel(`第${day + 1}份本节内容`);
        await expect(list.getByRole('button')).toHaveCount(sections[section]!.length);
        await expect(list.locator('[aria-current="step"]')).toHaveCount(1);
        for (const width of [1280, 390, 320]) {
          await page.setViewportSize({ width, height: 900 });
          await expect(list.getByRole('button').first()).toBeVisible();
          expect(
            await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth),
          ).toBe(true);
        }
        const last = list.getByRole('button').last();
        await last.focus();
        await last.press('Enter');
        await expect(last).toHaveAttribute('aria-current', 'step');
        await page.getByRole('button', { name: /停止示范/ }).click();
        if (section < sections.length - 1)
          await page.getByRole('button', { name: /^下一节/ }).click();
      }
      await page.getByRole('button', { name: '换练习', exact: true }).click();
    }
  });
}
