import { expect } from '@playwright/test';
import { test } from '../support/real-server';

for (const guest of [false, true]) {
  test(`GAME-02A: a stalled ${guest ? 'guest' : 'family'} clock request times out and can be retried`, async ({
    page,
    appUrl,
  }) => {
    await page.goto(appUrl);
    if (guest) await page.getByRole('button', { name: '访客体验', exact: true }).click();
    else {
      await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
      await page.getByRole('button', { name: '连接家庭' }).click();
    }
    await page.getByRole('button', { name: '进入游戏乐园' }).click();
    await page.getByRole('button', { name: '开始字形侦探' }).click();
    await expect(page.locator('.game-option').first()).toBeEnabled();
    const pattern = guest ? '**/api/v1/guest/operate' : '**/api/v1/games/heartbeat';
    await page.route(pattern, async (route) => {
      const isRenewal = !guest || route.request().postDataJSON().path === '/games/heartbeat';
      if (isRenewal) {
        await new Promise((resolve) => setTimeout(resolve, 9000));
        await route.continue().catch(() => {});
      } else await route.continue();
    });
    await expect(page.getByLabel('游戏已暂停')).toBeVisible({ timeout: 14000 });
    await expect(page.getByLabel('游戏已暂停')).toContainText('连接');
    await expect(page.locator('.game-option')).toHaveCount(0);
    await page.unroute(pattern);
    await page.getByRole('button', { name: '继续游戏', exact: true }).click();
    await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 10000 });
    await page.getByRole('button', { name: '退出练习' }).click();
    await expect(page.getByRole('heading', { name: '拼音游戏乐园', exact: true })).toBeVisible();
  });
}
