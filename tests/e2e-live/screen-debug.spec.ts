import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import { pairForHouseholdMaterial } from '../support/household-material';

test('WEB-DEBUG-01: real nested viewport, rotation, keyboard dismissal and unchanged platform', async ({
  page,
  appUrl,
}) => {
  await pairForHouseholdMaterial(page, appUrl);
  await page.getByRole('button', { name: '家长管理', exact: true }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await page.getByText('高级设置', { exact: true }).click();
  await page.getByRole('button', { name: '打开屏幕调试' }).click();
  const frame = page.frameLocator('iframe[title="屏幕交互预览"]');
  await expect(frame.getByRole('button', { name: '家长管理', exact: true })).toBeVisible();
  expect(await frame.locator('html').evaluate(() => innerWidth)).toBe(390);
  expect(await frame.locator('html').getAttribute('data-ios-app')).toBeNull();
  await page.getByRole('button', { name: '切换横竖屏' }).click();
  await expect.poll(() => frame.locator('html').evaluate(() => innerWidth)).toBe(844);
  await page.getByRole('combobox', { name: '预览屏幕' }).selectOption('desktop');
  await page.getByRole('button', { name: '切换横竖屏' }).click();
  await expect.poll(() => frame.locator('html').evaluate(() => innerWidth)).toBe(1280);
  await page.keyboard.press('Escape');
  await expect(page.getByRole('dialog', { name: 'Web 屏幕交互调试' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '打开屏幕调试' })).toBeFocused();
});

test('WEB-DEBUG-02: narrow lesson activity switch remains reachable after browsing long content', async ({
  page,
  appUrl,
}) => {
  await page.setViewportSize({ width: 320, height: 568 });
  await pairForHouseholdMaterial(page, appUrl);
  await page.getByRole('button', { name: '课堂学习', exact: true }).click();
  const tabs = page.getByRole('group', { name: '选择本课活动' });
  await page.locator('.lesson-pronunciation').scrollIntoViewIfNeeded();
  await expect(tabs.getByRole('button', { name: '写一写' })).toBeInViewport();
  await tabs.getByRole('button', { name: '写一写' }).click();
  await expect(page.getByRole('region', { name: '书写小课堂' })).toBeVisible();
  await expect(tabs.getByRole('button', { name: '练一练' })).toBeInViewport();
  await tabs.getByRole('button', { name: '练一练' }).click();
  await expect(page.getByRole('button', { name: '开始本课练习', exact: false })).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
});
