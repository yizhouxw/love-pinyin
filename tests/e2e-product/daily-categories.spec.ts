import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import daily from '../../content/daily-reading.json' with { type: 'json' };

test.use({ selectedPinyinSource: true });

test('DAILY-10: all fourteen materials show accurate categories; comparisons and spelling are not words', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('checkbox', { name: '语音引导', exact: true }).uncheck();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  const api = await (await page.request.get(`${appUrl}/api/v1/guest/daily-reading`)).json();
  expect(
    api.days.flatMap((d: { sections: { items: unknown[] }[] }) =>
      d.sections.flatMap((s) => s.items),
    ),
  ).toHaveLength(840);
  for (const day of daily.days) {
    await page.getByRole('button', { name: `第 ${day.number} 份`, exact: true }).click();
    await page.getByRole('button', { name: `开始第 ${day.number} 份跟读`, exact: true }).click();
    const nav = page.getByRole('navigation', { name: '本份小节', exact: true });
    for (const [index, section] of day.sections.entries()) {
      await nav.locator('.daily-section-tabs button').nth(index).click();
      const headings = page.getByLabel(`第${day.number}份本节内容`).locator('.daily-nav-heading');
      await expect(headings.first()).toBeVisible();
      const labels: Record<string, string> = {
        comparison: '辨音对比',
        spelling: '拼读组合',
        words: '词语',
        sentences: '句子',
      };
      if (section.kind !== 'phonics') {
        for (const heading of await headings.all())
          await expect(heading).toContainText(labels[section.kind]!);
      }
      await expect(page.locator('.daily-nav-heading').filter({ hasText: '词句' })).toHaveCount(0);
    }
    await page.getByRole('button', { name: '换练习', exact: true }).click();
  }
});

test('DAILY-10: reviewed word tails lead to real sentences with character pairs, audio and highlighting', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('checkbox', { name: '语音引导', exact: true }).uncheck();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  const reader = page.getByLabel('当前跟读内容', { exact: true });
  for (const [number, wordCount, lastWord, sentence] of [
    [11, 27, '柳条', '喵喵喵，小猫叫。'],
    [12, 24, '下雪', '喜鹊枝头叫，喜事就来到。'],
    [13, 18, '草原', '我每天都去爬山。'],
    [14, 24, '自行车', '我们上学去。'],
  ] as const) {
    await page.getByRole('button', { name: `第 ${number} 份`, exact: true }).click();
    await page.getByRole('button', { name: /^读词语/ }).click();
    const list = page.getByLabel(`第${number}份本节内容`);
    await expect(list.getByRole('button')).toHaveCount(wordCount);
    await list.getByRole('button').last().click();
    await expect(reader.locator('rt')).toHaveText([...lastWord]);
    await expect(reader.locator('.daily-highlight')).not.toHaveCount(0, { timeout: 15000 });
    await reader.getByRole('button', { name: '读过了，完成本节', exact: false }).click();
    await reader.getByRole('button', { name: '进入下一节 →', exact: true }).click();
    await expect(list.getByRole('button')).toHaveCount(3);
    await expect(reader.locator('rt')).toHaveText(
      sentence.match(/\p{Script=Han}[^\p{Script=Han}]*/gu)!,
    );
    await reader.getByRole('button', { name: /开始跟读/ }).click();
    await expect(reader.locator('.daily-highlight')).not.toHaveCount(0, { timeout: 15000 });
    await expect(
      page
        .getByRole('navigation', { name: '本份小节' })
        .getByRole('button', { name: '下一节', exact: true }),
    ).toBeDisabled();
    if (number === 14) {
      await page.setViewportSize({ width: 320, height: 844 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(
        false,
      );
      await page.screenshot({
        path: test.info().outputPath('daily14-sentences-320.png'),
        fullPage: true,
      });
    }
    await page.getByRole('button', { name: '换练习', exact: true }).click();
  }
});
