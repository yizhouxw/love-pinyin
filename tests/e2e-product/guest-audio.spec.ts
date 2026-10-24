import { openSection } from '../support/interaction';
import { expect } from '@playwright/test';
import { test } from '../support/real-server';

test.use({ selectedPinyinSource: true });

test('ACCESS-01: unpaired guest plays actual standard pronunciation and lesson recording', async ({
  page,
  appUrl,
  context,
}) => {
  test.setTimeout(30_000);
  const external: string[] = [];
  page.on('request', (request) => {
    if (request.url().startsWith('http') && new URL(request.url()).origin !== appUrl)
      external.push(request.url());
  });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验' }).click();
  await page.getByRole('button', { name: '课堂学习' }).click();
  const standard = page.waitForResponse(
    (response) =>
      response.url().includes('/guest/audio/') && [200, 206].includes(response.status()),
  );
  await openSection(page, '知识与教学提示');
  await page.getByRole('button', { name: 'a 播放标准音', exact: true }).click();
  const standardUrl = (await standard).url();
  await expect(page.getByRole('button', { name: 'a 停止播放', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'a 播放标准音', exact: true })).toBeVisible({
    timeout: 15_000,
  });
  const duration = await page.evaluate(async (url) => {
    const context = new AudioContext();
    try {
      const response = await fetch(url);
      const sound = await context.decodeAudioData(await response.arrayBuffer());
      return sound.duration;
    } finally {
      await context.close();
    }
  }, standardUrl);
  expect(duration).toBeGreaterThan(0.1);
  await page.getByRole('button', { name: '播放课程录音', exact: true }).click();
  await expect
    .poll(() =>
      page
        .getByLabel('课程录音播放进度')
        .evaluate((element: HTMLAudioElement) => element.currentTime),
    )
    .toBeGreaterThan(0.1);
  await page.getByRole('button', { name: '停止播放课程录音', exact: true }).click();
  expect((await context.cookies()).filter((cookie) => cookie.name.startsWith('lp_'))).toEqual([]);
  expect(external).toEqual([]);
});
