import { spawn } from 'node:child_process';
import { expect, type Page } from '@playwright/test';
import { test as realTest } from '../support/real-server';

const test = realTest.extend<{ devUrl: string }>({
  devUrl: async ({ appUrl }, use) => {
    const source = `import { createServer } from 'vite'; const server = await createServer({configFile:'config/vite.config.ts',server:{host:'127.0.0.1',port:0,proxy:{'/api':{target:process.argv[1]}}}}); await server.listen(); console.log('SHOP_URL='+server.resolvedUrls.local[0]);`;
    const child = spawn(process.execPath, ['--input-type=module', '-e', source, appUrl], {
      stdio: ['ignore', 'pipe', 'pipe'],
    });
    const closed = new Promise((resolve) => child.once('close', resolve));
    try {
      const url = await new Promise<string>((resolve, reject) => {
        let output = '';
        const timer = setTimeout(() => reject(new Error(output)), 20000);
        const collect = (data: Buffer) => {
          output += data.toString();
          const match = output.match(/SHOP_URL=(http:\/\/[^\s]+)/);
          if (match) {
            clearTimeout(timer);
            resolve(match[1]!);
          }
        };
        child.stdout.on('data', collect);
        child.stderr.on('data', collect);
        child.once('error', reject);
      });
      await use(url);
    } finally {
      child.kill('SIGTERM');
      await closed;
    }
  },
});
test.use({
  selectedPinyinSource: true,
  launchOptions: { args: ['--use-fake-ui-for-media-stream', '--use-fake-device-for-media-stream'] },
});
async function guest(page: Page, url: string) {
  await page.goto(url);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await expect(page.getByRole('button', { name: '进入游戏乐园', exact: false })).toBeVisible();
}
async function record(page: Page) {
  await expect(page.getByRole('button', { name: '开始录音', exact: false })).toBeEnabled({
    timeout: 20000,
  });
  await page.getByRole('button', { name: '开始录音', exact: false }).click();
  await expect(page.getByRole('button', { name: '完成录音', exact: false })).toBeVisible();
  await page.waitForTimeout(450);
  await page.getByRole('button', { name: '完成录音', exact: false }).click();
}

test('SHOP-01/03: production entry, actual guidance/standard audio, narrow shelf, shared pause and exit', async ({
  page,
  appUrl,
}) => {
  await guest(page, new URL('/?shopRecognition=mock', appUrl).href);
  await page.getByRole('button', { name: '进入游戏乐园', exact: false }).click();
  await page.getByRole('button', { name: '进入拼音小卖部', exact: false }).click();
  await expect(page.getByRole('heading', { name: '拼音小卖部', exact: true })).toBeVisible();
  await expect(page.getByText('真实识别尚未配置。', { exact: false })).toBeVisible();
  const sound = page.waitForResponse((r) => r.url().includes('/voice/ui-shop_ready') && r.ok());
  await page.getByRole('button', { name: '选择啊音礼盒', exact: true }).focus();
  await page.keyboard.press('Enter');
  await sound;
  await expect(page.getByRole('button', { name: '停止听操作提示', exact: true })).toHaveCount(0, {
    timeout: 20000,
  });
  await expect(page.locator('.shop-target')).toHaveText('a');
  await expect(page.locator('.shop-target')).toHaveCSS('font-family', /Andika Pinyin/);
  await expect(page.getByRole('button', { name: '开始录音', exact: false })).toBeDisabled();
  for (const width of [1280, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: test.info().outputPath(`shop-${width}.png`), fullPage: true });
  }
  await page.getByRole('button', { name: '暂停', exact: false }).click();
  await expect(page.getByLabel('游戏已暂停')).toBeVisible();
  await page.getByRole('button', { name: '继续游戏', exact: true }).click();
  await expect(page.getByLabel('拼音小卖部', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '结束本次购物', exact: true }).click();
  await expect(
    page.getByText('购物篮装好啦！看看你的收获，休息一下吧。', { exact: true }),
  ).toBeVisible();
  await page.getByRole('button', { name: '休息，回游戏乐园', exact: false }).click();
  await expect(page.getByLabel('拼音游戏乐园')).toBeVisible();
});

for (const mode of [
  'matched',
  'retry',
  'uncertain',
  'unavailable',
  'exception',
  'stale',
] as const) {
  test(`SHOP-02: captured WAV and controlled contract ${mode}`, async ({
    page,
    devUrl,
    browserName,
    context,
  }) => {
    test.skip(
      browserName !== 'chromium',
      'Chromium fake microphone exercises real capture; controlled port does not validate acoustic quality.',
    );
    await context.grantPermissions(['microphone']);
    await guest(page, devUrl);
    await page.goto(`${devUrl}tests/support/shop-harness.html?result=${mode}`);
    await page.getByRole('button', { name: '下一柜', exact: false }).click();
    await page.getByRole('button', { name: '选择米', exact: true }).click();
    await record(page);
    const feedback = page.locator('.shop-feedback');
    if (mode === 'matched') {
      await expect(page.getByLabel('我的购物篮')).toContainText('米');
      await expect(page.getByRole('button', { name: '选择米', exact: true })).toBeDisabled();
    } else {
      await expect(feedback).toContainText(
        mode === 'retry' ? '没有匹配' : mode === 'uncertain' ? '没有听清楚' : '暂不可用',
      );
      await expect(page.getByLabel('我的购物篮')).toContainText('0 / 6');
      await expect(page.getByRole('button', { name: '选择米', exact: true })).toBeEnabled();
    }
  });
}

test('SHOP-02/03: late response after switching product, pause and timeout cannot add an item', async ({
  page,
  devUrl,
  browserName,
  context,
}) => {
  test.skip(browserName !== 'chromium', 'Requires Chromium fake microphone.');
  await context.grantPermissions(['microphone']);
  await guest(page, devUrl);
  await page.goto(`${devUrl}tests/support/shop-harness.html?delay=2200`);
  await page.getByRole('button', { name: '下一柜', exact: false }).click();
  await page.getByRole('button', { name: '选择米', exact: true }).click();
  await record(page);
  await expect(page.locator('.shop-feedback')).toContainText('正在核对');
  await page.getByRole('button', { name: '选择布', exact: true }).click();
  await page.waitForTimeout(2600);
  await expect(page.getByLabel('我的购物篮')).toContainText('0 / 6');
  await expect(page.locator('.shop-target')).toHaveText('bù');
  await record(page);
  await page.getByRole('button', { name: '暂停', exact: false }).click();
  await page.waitForTimeout(2500);
  await page.getByRole('button', { name: '继续游戏', exact: true }).click();
  await expect(page.getByLabel('我的购物篮')).toContainText('0 / 6');
  await page.goto(`${devUrl}tests/support/shop-harness.html?delay=20000`);
  await page.getByRole('button', { name: '下一柜', exact: false }).click();
  await page.getByRole('button', { name: '选择米', exact: true }).click();
  await record(page);
  await expect(page.locator('.shop-feedback')).toContainText('暂不可用', { timeout: 19000 });
  await expect(page.getByLabel('我的购物篮')).toContainText('0 / 6');
});

test('SHOP-01/02: six-item basket completes once and mock remains explicitly marked', async ({
  page,
  devUrl,
  browserName,
  context,
}) => {
  test.skip(browserName !== 'chromium', 'Requires Chromium fake microphone.');
  await context.grantPermissions(['microphone']);
  await guest(page, devUrl);
  await page.goto(`${devUrl}tests/support/shop-harness.html?evidence=mock`);
  await expect(page.getByText('开发模拟演示', { exact: true })).toBeVisible();
  const products = page.locator('.shop-product');
  for (let index = 0; index < 6; index++) {
    await products.nth(index).click();
    await record(page);
    await expect(page.getByLabel('我的购物篮').locator('li')).toHaveCount(index + 1);
  }
  await expect(page.getByText('模拟购物清单', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '休息，回游戏乐园', exact: false })).toBeVisible();
  await expect(products.nth(5)).toBeDisabled();
});

test('SHOP-03: microphone rejection recovers and game lease failure cancels a pending match', async ({
  page,
  devUrl,
  browserName,
  context,
}) => {
  test.skip(browserName !== 'chromium', 'Requires Chromium fake microphone.');
  await context.grantPermissions(['microphone']);
  await guest(page, devUrl);
  await page.addInitScript(() => {
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    let rejected = false;
    navigator.mediaDevices.getUserMedia = (constraints) => {
      if (!rejected) {
        rejected = true;
        return Promise.reject(new DOMException('test denied', 'NotAllowedError'));
      }
      return original(constraints);
    };
  });
  await page.goto(`${devUrl}tests/support/shop-harness.html?delay=10000`);
  await page.getByRole('button', { name: '下一柜', exact: false }).click();
  await page.getByRole('button', { name: '选择米', exact: true }).click();
  await expect(page.getByRole('button', { name: '开始录音', exact: false })).toBeEnabled({
    timeout: 20000,
  });
  await page.getByRole('button', { name: '开始录音', exact: false }).click();
  await expect(page.locator('.shop-feedback')).toContainText('没有录到声音');
  await record(page);
  await page.route('**/api/v1/guest/operate', async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    const operation = route.request().postDataJSON() as { path: string };
    await route.fulfill({
      response,
      json:
        operation.path === '/games/heartbeat'
          ? { ...body, result: { ...body.result, reason: 'GAME_DAILY_LIMIT', leaseSeconds: 0 } }
          : body,
    });
  });
  await expect(page.getByLabel('游戏已暂停')).toBeVisible({ timeout: 10000 });
  await expect(page.getByText('该休息一下啦', { exact: true })).toBeVisible();
  await page.unroute('**/api/v1/guest/operate');
  await page.waitForTimeout(10500);
  await page.getByRole('button', { name: '休息后检查时间', exact: true }).click();
  await expect(page.getByLabel('我的购物篮')).toContainText('0 / 6');
});
