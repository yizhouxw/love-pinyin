import { expect } from '@playwright/test';
import product from '../../package.json' with { type: 'json' };
import { test } from '../support/real-server';

test('SPEC016 VERSION-01: local history opens on pairing and learning and returns keyboard focus', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  const version = page.getByRole('button', { name: `版本 ${product.version}`, exact: true }).last();
  await version.click();
  const dialog = page.getByRole('dialog', { name: '爱拼音 · 版本与更新' });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText(`产品版本 ${product.version}`);
  await expect(dialog).toContainText('未追补此前版本的发布日期');
  await page.keyboard.press('Escape');
  await expect(dialog).not.toBeVisible();
  await expect(version).toBeFocused();
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await version.click();
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText('教学内容版本');
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await expect(dialog.getByRole('button', { name: '关闭', exact: true })).toBeInViewport();
    await page.screenshot({ path: test.info().outputPath(`version-${width}.png`) });
  }
  await dialog.getByRole('button', { name: '关闭', exact: true }).click();
  await expect(version).toBeFocused();
});

test('SPEC016 UX01/08: optional pairing detail stays folded and invalid code gives nearby recovery', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await expect(page.getByLabel('设备型号（可修改）')).not.toBeVisible();
  await page.getByLabel('家长配对码', { exact: true }).fill('ZZZZZZZZ');
  await page.getByRole('button', { name: '连接家庭', exact: true }).click();
  const error = page.locator('.pair-page form').getByRole('alert');
  await expect(error).toContainText('配对码已失效或输入有误');
  await expect(error).toContainText('重新生成');
  await expect(error.getByText('PAIRING_CODE_INVALID', { exact: true })).not.toBeVisible();
  await error.getByText('技术详情', { exact: true }).click();
  await expect(error.getByText('PAIRING_CODE_INVALID', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭', exact: true }).click();
  await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeVisible();
  await page.getByRole('button', { name: '家长管理', exact: true }).click();
  await page.getByRole('button', { name: '我是家长，继续', exact: true }).click();
  for (const width of [1280, 390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await expect(page.getByRole('combobox', { name: '当前课程', exact: true })).toBeInViewport();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: test.info().outputPath(`parent-${width}.png`), fullPage: true });
  }
});

test('SPEC016 UX08: reconnecting a failed pairing request does not submit the form again', async ({
  page,
  appUrl,
}) => {
  let pairRequests = 0;
  await page.route('**/api/v1/pair', (route) => {
    pairRequests += 1;
    return route.abort('failed');
  });
  await page.goto(appUrl);
  await page.getByLabel('家长配对码', { exact: true }).fill('ZZZZZZZZ');
  await page.getByRole('button', { name: '连接家庭', exact: true }).click();
  const recovery = page.getByRole('button', { name: '重新连接并恢复', exact: true });
  await expect(recovery).toBeVisible();
  expect(pairRequests).toBe(1);
  const bootstrap = page.waitForResponse((response) => response.url().endsWith('/bootstrap'));
  await recovery.click();
  await bootstrap;
  await expect(recovery).not.toBeVisible();
  expect(pairRequests).toBe(1);
});
