import { expect, type Page } from '@playwright/test';
import { pairForHouseholdMaterial, useHouseholdMaterial } from '../support/household-material';
import { test } from '../support/real-server';

test.use({ selectedPinyinSource: true });

async function chooseSpelling(page: Page) {
  const spelling = page.getByRole('button', { name: '拼读', exact: true });
  if (!(await spelling.isVisible())) {
    await page.getByText('播放设置', { exact: true }).click();
  }
  await spelling.click();
}

test('DAILY-15 / WORD-13: both practices request the final with the target tone', async ({
  page,
  appUrl,
}) => {
  await pairForHouseholdMaterial(page, appUrl);
  await page.getByRole('button', { name: '进入词语天天练 →' }).click();
  await page.getByRole('button', { name: /^选择课程/ }).click();
  const picker = page.getByRole('dialog');
  await picker.getByRole('button', { name: '第6单元', exact: true }).click();
  await picker.getByRole('button', { name: '选择语文园地六', exact: true }).click();
  await chooseSpelling(page);

  const wordFinal = page.waitForResponse(
    (response) => response.url().endsWith('/daily-audio/spelling-final-ao3') && response.ok(),
  );
  await page.getByRole('button', { name: '听读老师', exact: true }).click();
  expect((await wordFinal).headers()['content-type']).toBe('audio/mpeg');
  await expect(page.locator('.word-playback')).not.toContainText('正在播放', { timeout: 15000 });
  await expect(page.locator('.word-audio-error')).toHaveAttribute('aria-hidden', 'true');

  await page.getByRole('button', { name: '返回首页' }).click();
  await useHouseholdMaterial(page);
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: '第 3 份', exact: true }).click();
  await page.getByRole('button', { name: /读词语/ }).click();
  await chooseSpelling(page);
  // Check the real spelling demonstration in isolation from the optional follow-up narration.
  await page.getByRole('checkbox', { name: '语音引导', exact: true }).uncheck();
  await expect(page.locator('.daily-target')).toContainText('bà');
  const dailyFinal = page.waitForResponse(
    (response) => response.url().endsWith('/daily-audio/spelling-final-a4') && response.ok(),
  );
  await page.getByRole('button', { name: '开始跟读' }).click();
  expect((await dailyFinal).headers()['content-type']).toBe('audio/mpeg');
  await expect(page.locator('.daily-status-strip')).toContainText('轮到你读啦', { timeout: 15000 });
});
