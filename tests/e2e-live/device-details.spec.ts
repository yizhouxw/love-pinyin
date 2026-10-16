import { expect } from '@playwright/test';
import { test } from '../support/real-server';

test('DEVICE-01: real paired devices show editable model, consumed code, connection time and copy feedback', async ({
  page,
  appUrl,
  browser,
}) => {
  await page.goto(appUrl);
  await page.getByLabel('设备型号（可修改）').fill('Mac Studio 家长电脑');
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  await expect(page.getByLabel('家长配对码', { exact: true })).toHaveValue(/^[A-Z2-9]{8}$/);
  const parentCode = await page.getByLabel('家长配对码', { exact: true }).inputValue();
  await page.getByRole('button', { name: '连接家庭' }).click();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  const rows = page.locator('.device-list li');
  await expect(rows).toHaveCount(1);
  await expect(rows.first()).toContainText('设备型号：Mac Studio 家长电脑');
  await expect(rows.first()).toContainText(/最后连接服务：.*\d{2}:\d{2}:\d{2}/);
  await expect(rows.first().getByRole('textbox', { name: '学习设备的已用配对码' })).toHaveValue(
    parentCode,
  );
  await expect(rows.first()).toContainText('已使用，不能再次配对');
  await rows.first().getByText('修改设备型号', { exact: true }).click();
  await rows.first().getByLabel('设备型号', { exact: true }).fill('Mac Studio M2 Max');
  await rows.first().getByRole('button', { name: '保存设备型号' }).click();
  await expect(rows.first()).toContainText('设备型号：Mac Studio M2 Max');
  await page.getByRole('button', { name: '生成配对码', exact: true }).click();
  const invitation = await page
    .getByRole('region', { name: '配对码管理' })
    .getByLabel('新生成的配对码')
    .inputValue();
  const childContext = await browser.newContext();
  try {
    const child = await childContext.newPage();
    await child.goto(appUrl);
    await child.getByLabel('家长配对码', { exact: true }).fill(invitation);
    await child.getByLabel('设备型号（可修改）').fill('iPad Air 5');
    await child.getByRole('button', { name: '连接家庭' }).click();
    await expect(child.getByLabel('家庭模式', { exact: true })).toContainText('学习设备');
    await page.getByRole('button', { name: '刷新设备列表' }).click();
    await expect(rows).toHaveCount(2);
    const ipad = rows.filter({ hasText: '设备型号：iPad Air 5' });
    await expect(ipad).toContainText(/最后连接服务：.*\d{2}:\d{2}:\d{2}/);
    await expect(ipad.getByRole('textbox')).toHaveValue(invitation);
    await page.evaluate(() => {
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: {
          writeText: async (value: string) => {
            sessionStorage.setItem('test.copied-code', value);
          },
        },
      });
    });
    await ipad.getByRole('button', { name: '复制配对码' }).click();
    await expect(ipad.getByRole('status')).toHaveText('已复制');
    expect(await page.evaluate(() => sessionStorage.getItem('test.copied-code'))).toBe(invitation);
    await page.evaluate(() => {
      Object.defineProperty(navigator, 'clipboard', {
        configurable: true,
        value: {
          writeText: async () => {
            throw new Error('permission denied');
          },
        },
      });
    });
    await ipad.getByRole('button', { name: '复制配对码' }).click();
    await expect(ipad.getByRole('status')).toContainText('自动复制不可用');
    await expect(ipad.getByRole('textbox')).toHaveValue(invitation);
    expect(
      await ipad
        .getByRole('textbox')
        .evaluate((input: HTMLInputElement) => [input.selectionStart, input.selectionEnd]),
    ).toEqual([0, 8]);
    await page.screenshot({
      path: test.info().outputPath('connected-device-details.png'),
      fullPage: true,
    });
    await page.reload();
    await page.getByRole('button', { name: '家长管理' }).click();
    await page.getByRole('button', { name: '我是家长，继续' }).click();
    await expect(rows.filter({ hasText: 'Mac Studio M2 Max' })).toHaveCount(1);
  } finally {
    await childContext.close();
  }
});
