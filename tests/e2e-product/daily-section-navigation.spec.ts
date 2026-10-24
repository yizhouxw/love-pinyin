import { expect, type Page } from '@playwright/test';
import daily from '../../content/daily-reading.json' with { type: 'json' };
import { test } from '../support/real-server';
import { clearReadingMedia, observeReadingMedia, playedReading } from '../support/media-log';

test.use({ selectedPinyinSource: true });

async function enter(page: Page, appUrl: string, number: number) {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: `第 ${number} 份`, exact: true }).click();
  await page.getByRole('button', { name: `开始第 ${number} 份跟读`, exact: true }).click();
}

test('DAILY-09: direct and adjacent section navigation cancel real playback and preserve practice marks', async ({
  page,
  appUrl,
}) => {
  await observeReadingMedia(page);
  await enter(page, appUrl, 3);
  const day = daily.days[2]!;
  const nav = page.getByRole('navigation', { name: '本份小节', exact: true });
  const tabs = nav.locator('.daily-section-tabs button');
  const reader = page.getByLabel('当前跟读内容', { exact: true });
  await expect(page.getByText('本份声音已就绪。', { exact: true })).toBeVisible();
  // Prepared resources must survive section changes within this material.
  await page.route('**/api/v1/guest/daily-audio/**', (route) => route.abort('failed'));
  await page.route('**/api/v1/guest/voice/daily-*', (route) => route.abort('failed'));
  await expect(tabs).toHaveCount(day.sections.length);
  await expect(nav.getByRole('button', { name: '上一节', exact: true })).toBeDisabled();
  await page.getByRole('checkbox', { name: '语音引导', exact: true }).uncheck();
  await reader.getByRole('button', { name: '读过了，下一条', exact: false }).click();
  await expect(tabs.first()).toContainText(`练过 1 / ${day.sections[0]!.items.length} 条`);
  // Selecting the already current section should not reset the current item.
  await tabs.first().click();
  await expect(reader.locator('.daily-reader-top strong')).toHaveText(
    `第 2 / ${day.sections[0]!.items.length} 条`,
  );
  await reader.getByRole('button', { name: '连播本节', exact: false }).click();
  await expect.poll(() => playedReading(page, 'daily-audio')).not.toHaveLength(0);
  await nav.getByRole('button', { name: '下一节', exact: true }).click();
  await expect(tabs.nth(1)).toHaveAttribute('aria-current', 'step');
  await expect(tabs.nth(1)).toBeFocused();
  await expect(reader.locator('.daily-reader-top strong')).toHaveText(
    `第 1 / ${day.sections[1]!.items.length} 条`,
  );
  await expect(page.getByRole('button', { name: '停止示范', exact: false })).toHaveCount(0);
  await clearReadingMedia(page);
  // Wait past an old clip/gap boundary: no abandoned queue may start another sound.
  await page.waitForTimeout(2500);
  expect(await playedReading(page, 'daily-audio')).toEqual([]);
  await reader.getByRole('button', { name: '开始跟读', exact: false }).click();
  await expect.poll(() => playedReading(page, 'daily-audio')).not.toHaveLength(0);
  await expect(reader.getByRole('button', { name: '停止示范', exact: false })).toHaveCount(0);
  await page.evaluate(() => window.scrollTo({ top: 0, behavior: 'instant' }));
  await nav.screenshot({ path: test.info().outputPath('section-navigation.png') });
  await page.screenshot({ path: test.info().outputPath('section-reading.png'), fullPage: true });
  await tabs.first().press('Enter');
  await expect(tabs.first()).toHaveAttribute('aria-current', 'step');
  await expect(tabs.first()).toContainText('练过 1 /');
  await expect(page.getByRole('checkbox', { name: '语音引导', exact: true })).not.toBeChecked();
  const items = page.getByLabel('第3份本节内容').getByRole('button');
  await items.last().click();
  await reader.getByRole('button', { name: '读过了，完成本节', exact: false }).click();
  await reader.getByRole('button', { name: '进入下一节', exact: false }).click();
  await expect(tabs.nth(1)).toHaveAttribute('aria-current', 'step');
  await tabs.last().click();
  await expect(nav.getByRole('button', { name: '下一节', exact: true })).toBeDisabled();
  await page.getByLabel('第3份本节内容').getByRole('button').last().click();
  await reader.getByRole('button', { name: '读过了，完成本节', exact: false }).click();
  await reader.getByRole('button', { name: '返回本份目录', exact: true }).click();
  await expect(page.getByRole('navigation', { name: '选择练习小节' })).toBeVisible();
  const state = await page.evaluate(() => JSON.parse(sessionStorage.getItem('lp.guest.v1')!).state);
  expect(state.attempts).toEqual([]);
});

test('DAILY-09: every material exposes all sections and keeps current tabs visible at narrow widths', async ({
  page,
  appUrl,
}) => {
  await enter(page, appUrl, 1);
  const nav = page.getByRole('navigation', { name: '本份小节', exact: true });
  const tabs = nav.locator('.daily-section-tabs button');
  for (const day of daily.days) {
    if (day.number !== 1) {
      await page.getByRole('button', { name: '换练习', exact: true }).click();
      await page.getByRole('button', { name: `第 ${day.number} 份`, exact: true }).click();
      await page.getByRole('button', { name: `开始第 ${day.number} 份跟读`, exact: true }).click();
    }
    await expect(tabs).toHaveCount(day.sections.length);
    for (const [index, section] of day.sections.entries())
      await expect(tabs.nth(index)).toContainText(section.title);
    await expect(nav.getByRole('button', { name: '上一节', exact: true })).toBeDisabled();
    if (day.sections.length === 1)
      await expect(nav.getByRole('button', { name: '下一节', exact: true })).toBeDisabled();
    await tabs.last().press('Enter');
    await expect(tabs.last()).toHaveAttribute('aria-current', 'step');
    await expect(nav.getByRole('button', { name: '下一节', exact: true })).toBeDisabled();
  }
  for (const width of [1280, 390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await expect(tabs.last()).toBeFocused();
    await expect(nav.getByRole('button', { name: '上一节', exact: true })).toBeInViewport();
    await expect
      .poll(async () => {
        const viewport = (await nav.locator('.daily-section-tabs').boundingBox())!;
        const active = (await tabs.last().boundingBox())!;
        return active.x >= viewport.x && active.x + active.width <= viewport.x + viewport.width + 1;
      })
      .toBe(true);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({
      path: test.info().outputPath(`sections-${width}.png`),
      fullPage: true,
    });
    await nav.getByRole('button', { name: '上一节', exact: true }).click();
    await expect(tabs.nth(daily.days.at(-1)!.sections.length - 2)).toHaveAttribute(
      'aria-current',
      'step',
    );
    await nav.getByRole('button', { name: '下一节', exact: true }).click();
  }
  await tabs.nth(1).press('Enter');
  await expect(tabs.nth(1)).toHaveAttribute('aria-current', 'step');
  await expect(tabs.nth(1)).toBeInViewport({ ratio: 1 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({
    path: test.info().outputPath('sections-long-title-320.png'),
    fullPage: true,
  });
});

test('DAILY-09: changing section discards a pending microphone permission result', async ({
  page,
  appUrl,
}) => {
  await enter(page, appUrl, 3);
  await page.getByRole('checkbox', { name: '语音引导', exact: true }).uncheck();
  await page.evaluate(() => {
    const state = window as Window & {
      allowSectionMic?: () => void;
      sectionStream?: MediaStream;
      sectionContext?: AudioContext;
    };
    const context = new AudioContext();
    const stream = context.createMediaStreamDestination().stream;
    state.sectionStream = stream;
    state.sectionContext = context;
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: () =>
          new Promise<MediaStream>((resolve) => {
            state.allowSectionMic = () => resolve(stream);
          }),
      },
    });
  });
  await page.getByText('录音比较（可选）', { exact: true }).click();
  await page.getByRole('button', { name: '录下我的跟读', exact: false }).click();
  await expect(page.getByLabel('当前跟读内容').getByRole('status')).toContainText('正在准备录音');
  await page
    .getByRole('navigation', { name: '本份小节', exact: true })
    .getByRole('button', { name: '下一节', exact: true })
    .click();
  await page.evaluate(() =>
    (window as Window & { allowSectionMic?: () => void }).allowSectionMic!(),
  );
  await expect
    .poll(() =>
      page.evaluate(() =>
        (window as Window & { sectionStream?: MediaStream })
          .sectionStream!.getTracks()
          .every((track) => track.readyState === 'ended'),
      ),
    )
    .toBe(true);
  await expect(page.getByRole('button', { name: '停止录音', exact: false })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '开始跟读', exact: false })).toBeEnabled();
  await expect(page.getByLabel('回放我的跟读')).toHaveCount(0);
  await page.evaluate(() =>
    (window as Window & { sectionContext?: AudioContext }).sectionContext!.close(),
  );
});
