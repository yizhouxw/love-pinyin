import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import { observeReadingMedia, clearReadingMedia } from '../support/media-log';
import { openSection } from '../support/interaction';

test.use({ selectedPinyinSource: true });

test('WRITE-04: names single targets, repeats the introduction during continuous playback and cancels', async ({
  page,
  appUrl,
}) => {
  await observeReadingMedia(page);
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '课堂学习' }).click();
  await page.getByRole('button', { name: '写一写', exact: true }).click();
  await clearReadingMedia(page);
  await page.getByRole('checkbox', { name: '连读', exact: true }).check();
  await page.getByRole('button', { name: '观察 a 的书写', exact: true }).click();
  const started = () =>
    page.evaluate(() =>
      window.readingMediaEvents
        .filter((e) => e.type === 'start')
        .map((e) => e.source.split('/').at(-1)),
    );
  await expect
    .poll(started, { timeout: 20000 })
    .toEqual(['writing-ui-start', 'audio-final-a', 'writing-v1-a-placement']);
  await expect
    .poll(async () => (await started()).slice(-2), { timeout: 45000 })
    .toEqual(['writing-ui-start', 'audio-final-o']);
  await page.getByRole('button', { name: '■ 停止演示' }).click();
  const stopped = await started();
  await page.waitForTimeout(1800);
  expect(await started()).toEqual(stopped);
  await page.getByRole('checkbox', { name: '连读', exact: true }).uncheck();
  await clearReadingMedia(page);
  await page.getByRole('button', { name: '▶ 播放笔顺' }).click();
  await expect.poll(started, { timeout: 20000 }).toEqual(['writing-ui-start', 'audio-final-o']);
  await page.getByRole('button', { name: '观察 e 的书写', exact: true }).click();
  await expect
    .poll(async () => (await started()).slice(-2), { timeout: 15000 })
    .toEqual(['writing-ui-start', 'audio-final-e']);
  await page.getByRole('checkbox', { name: '语音引导', exact: true }).uncheck();
  await clearReadingMedia(page);
  await page.getByRole('button', { name: '▶ 播放笔顺' }).click();
  await expect(page.locator('.writing-instruction')).toContainText('第 1 / 1 笔');
  expect(await started()).toEqual([]);
});

test('WRITE-04: combination names its written letters before strokes; marked target uses its actual tone', async ({
  page,
  appUrl,
}) => {
  await observeReadingMedia(page);
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await openSection(page, '查看全部课程');
  await page.getByRole('button', { name: /^11 / }).click();
  await page.getByRole('button', { name: '写一写', exact: true }).click();
  await clearReadingMedia(page);
  await page.getByRole('button', { name: '观察 ao 的书写', exact: true }).click();
  const started = () =>
    page.evaluate(() =>
      window.readingMediaEvents
        .filter((e) => e.type === 'start')
        .map((e) => e.source.split('/').at(-1)),
    );
  await expect
    .poll(started, { timeout: 35000 })
    .toEqual([
      'writing-ui-start',
      'audio-final-ao',
      'writing-ui-composition',
      'audio-final-a',
      'writing-ui-and',
      'audio-final-o',
      'writing-ui-joined',
      'writing-v1-a-placement',
    ]);
  await page.getByRole('button', { name: '带声调', exact: true }).click();
  await page.getByRole('button', { name: '■ 停止演示' }).click();
  await clearReadingMedia(page);
  await page.getByRole('button', { name: '观察 jiǔ 的书写', exact: true }).click();
  await expect
    .poll(async () => (await started()).slice(0, 3), { timeout: 15000 })
    .toEqual(['writing-ui-start', 'daily-jiu3', 'writing-ui-composition']);
  await page.getByRole('button', { name: '听一听', exact: true }).click();
  const stopped = await started();
  await page.waitForTimeout(1800);
  expect(await started()).toEqual(stopped);
});

test('WRITE-04: an unavailable target name stops the explanation; retry starts with the name again', async ({
  page,
  appUrl,
}) => {
  await observeReadingMedia(page);
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '课堂学习' }).click();
  await page.getByRole('button', { name: '写一写', exact: true }).click();
  await page.route('**/audio/audio-final-e', (route) => route.abort('failed'));
  await clearReadingMedia(page);
  await page.getByRole('button', { name: '观察 e 的书写', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('声音没有播放成功');
  await expect(page.locator('.writing-stage .active')).toHaveCount(0);
  expect(
    await page.evaluate(() =>
      window.readingMediaEvents
        .filter((e) => e.type === 'start')
        .map((e) => e.source.split('/').at(-1)),
    ),
  ).toEqual(['writing-ui-start']);
  await page.unroute('**/audio/audio-final-e');
  await clearReadingMedia(page);
  await page.getByRole('button', { name: '▶ 播放笔顺' }).click();
  await expect
    .poll(
      () =>
        page.evaluate(() =>
          window.readingMediaEvents
            .filter((e) => e.type === 'start')
            .map((e) => e.source.split('/').at(-1)),
        ),
      { timeout: 15000 },
    )
    .toEqual(['writing-ui-start', 'audio-final-e', 'writing-v1-e-placement']);
});
