import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import { observeReadingMedia, clearReadingMedia, playedReading } from '../support/media-log';

declare global {
  interface Window {
    sentenceMedia?: HTMLMediaElement;
  }
}
test.use({ selectedPinyinSource: true });

test('DAILY-11: complete sentences default to connected reading; character mode adds real pauses and cancels old playback', async ({
  page,
  appUrl,
}) => {
  await observeReadingMedia(page);
  await page.addInitScript(() => {
    const play = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () {
      if (this.getAttribute('data-learning-source')?.includes('/voice/daily-sentence-'))
        window.sentenceMedia = this;
      return play.call(this);
    };
  });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('checkbox', { name: '语音引导', exact: true }).uncheck();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  const data = await (await page.request.get(`${appUrl}/api/v1/guest/daily-reading`)).json();
  const sentences = data.days.flatMap(
    (d: {
      sections: {
        kind: string;
        items: {
          sentenceReading: {
            available: boolean;
            narrationId: string;
            timings: { start: number; end: number }[];
          };
          syllables: string[];
        }[];
      }[];
    }) => d.sections.filter((s) => s.kind === 'sentences').flatMap((s) => s.items),
  );
  expect(sentences).toHaveLength(21);
  expect(
    sentences.every(
      (i: { sentenceReading: { available: boolean } }) => i.sentenceReading.available,
    ),
  ).toBe(true);
  await page.getByRole('button', { name: '第 14 份', exact: true }).click();
  await page.getByRole('button', { name: /^读句子/ }).click();
  await expect(page.getByText('本份声音已就绪。', { exact: true })).toBeVisible();
  const reader = page.getByLabel('当前跟读内容', { exact: true });
  const mode = reader.getByRole('checkbox', { name: '逐字读', exact: true });
  await expect(mode).not.toBeChecked();
  await expect(reader).toContainText('整句连读 · 普通话示范');
  await clearReadingMedia(page);
  await reader.getByRole('button', { name: /开始跟读/ }).click();
  await expect.poll(() => playedReading(page, 'voice')).toEqual(['daily-sentence-day-14-s7-i7']);
  await expect(reader.locator('.daily-highlight')).not.toHaveCount(0);
  const wholeDuration = await page.evaluate(() => window.sentenceMedia!.duration);
  await mode.check();
  await expect(reader.getByRole('button', { name: /开始跟读/ })).toBeVisible();
  await expect(reader.locator('.daily-highlight')).toHaveCount(0);
  await page.route('**/api/v1/guest/voice/**', (route) => route.abort('failed'));
  await reader.getByRole('button', { name: /开始跟读/ }).click();
  await expect
    .poll(() => page.evaluate(() => window.sentenceMedia!.duration))
    .toBeCloseTo(wholeDuration + 1.6, 1);
  const first = sentences.at(-3)!;
  const boundary = first.sentenceReading.timings[1]!.start;
  await page.waitForFunction(
    ({ boundary }) => {
      const media = window.sentenceMedia;
      return (
        media &&
        media.currentTime > boundary + 0.03 &&
        media.currentTime < boundary + 0.37 &&
        document.querySelectorAll('.daily-highlight').length === 0
      );
    },
    { boundary },
  );
  await expect(reader).toContainText('逐字读 · 字间留停顿');
  await reader.getByRole('button', { name: /停止示范/ }).click();
  await expect(reader.locator('.daily-highlight')).toHaveCount(0);
  await page
    .getByRole('navigation', { name: '本份小节' })
    .getByRole('button', { name: '上一节', exact: true })
    .click();
  await expect(page.getByRole('checkbox', { name: '逐字读', exact: true })).toHaveCount(0);
  await page
    .getByRole('navigation', { name: '本份小节' })
    .getByRole('button', { name: '下一节', exact: true })
    .click();
  await expect(page.getByRole('checkbox', { name: '逐字读', exact: true })).toBeChecked();
  await page.setViewportSize({ width: 320, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)).toBe(false);
  await page.screenshot({ path: test.info().outputPath('sentence-modes-320.png'), fullPage: true });
  await page.getByRole('button', { name: /返回小岛/ }).click();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: '第 14 份', exact: true }).click();
  await page.getByRole('button', { name: /^读句子/ }).click();
  await expect(page.getByRole('checkbox', { name: '逐字读', exact: true })).not.toBeChecked();
});

test('DAILY-11: queued sentences keep the chosen mode; pending recording locks the switch', async ({
  page,
  appUrl,
}) => {
  await observeReadingMedia(page);
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('checkbox', { name: '语音引导', exact: true }).uncheck();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: '第 5 份', exact: true }).click();
  await page.getByRole('button', { name: /^拼读句子/ }).click();
  const reader = page.getByLabel('当前跟读内容', { exact: true });
  const mode = reader.getByRole('checkbox', { name: '逐字读', exact: true });
  await mode.check();
  await clearReadingMedia(page);
  await reader.getByRole('button', { name: /连播本节/ }).click();
  await expect
    .poll(async () => (await playedReading(page, 'voice')).slice(0, 2), { timeout: 30000 })
    .toEqual(['daily-word-day-05-s5-i1', 'daily-sentence-day-05-s5-i2']);
  await expect(mode).toBeChecked();
  await reader.getByRole('button', { name: /停止示范/ }).click();
  await page.evaluate(() => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: () => new Promise(() => {}) },
    });
  });
  await reader.getByText('录音比较（可选）', { exact: true }).click();
  await reader.getByRole('button', { name: /录下我的跟读/ }).click();
  await expect(mode).toBeDisabled();
  await expect(reader.getByRole('status')).toContainText('正在准备录音');
  await page.getByRole('button', { name: '换练习', exact: true }).click();
  await page.getByRole('button', { name: /^拼读句子/ }).click();
  await expect(page.getByRole('checkbox', { name: '逐字读', exact: true })).toBeEnabled();
});
