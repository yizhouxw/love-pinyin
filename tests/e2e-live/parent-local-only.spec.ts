import { expect } from '@playwright/test';
import { test } from '../support/real-server';

test('ACCESS-03: non-127 host cannot open parent management even with an existing parent cookie', async ({
  page,
  appUrl,
  browser,
  context,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭' }).click();
  await expect(page.getByRole('button', { name: '家长管理' })).toBeVisible();
  const remoteUrl = appUrl.replace('127.0.0.1', 'localhost');
  const remoteContext = await browser.newContext();
  try {
    const cookies = await context.cookies();
    await remoteContext.addCookies(
      cookies.map((cookie) => ({ name: cookie.name, value: cookie.value, url: remoteUrl })),
    );
    const remote = await remoteContext.newPage();
    await remote.goto(remoteUrl);
    await expect(remote.getByRole('button', { name: '开始今天的练习' })).toBeVisible();
    await expect(remote.getByLabel('家庭模式', { exact: true })).toContainText(
      '进度已连接家庭 Mac',
    );
    expect(
      (await (await remote.request.get(new URL('/api/v1/bootstrap', remote.url()).href)).json())
        .device.isParent,
    ).toBe(false);
    await expect(remote.getByRole('button', { name: '家长管理' })).toHaveCount(0);
    await expect(remote.getByRole('dialog')).toHaveCount(0);
    await expect(remote.getByRole('region', { name: '配对码管理' })).toHaveCount(0);
    expect((await remote.request.get(remoteUrl + '/api/v1/devices')).status()).toBe(403);
    const csrf = cookies.find((cookie) => cookie.name === 'lp_csrf')!.value;
    expect(
      (
        await remote.request.post(remoteUrl + '/api/v1/pairing-codes', {
          headers: { 'X-LP-CSRF': csrf, 'X-Forwarded-For': '127.0.0.1' },
        })
      ).status(),
    ).toBe(403);
    await remoteContext.clearCookies();
    await remote.reload();
    await expect(remote.getByRole('button', { name: '在 Mac 上生成家长配对码' })).toHaveCount(0);
    await remote.getByRole('button', { name: '访客体验' }).click();
    await expect(remote.getByLabel('访客模式', { exact: true })).toBeVisible();
    await expect(remote.getByRole('button', { name: '家长管理' })).toHaveCount(0);
    await remote.getByRole('button', { name: '清除并退出访客' }).click();
    await expect(remote.getByRole('button', { name: '连接家庭', exact: true })).toBeVisible();
  } finally {
    await remoteContext.close();
  }
});
