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

async function openHarness(page: Page, devUrl: string, query = '') {
  await guest(page, devUrl);
  await page.goto(`${devUrl}tests/support/shop-harness.html?${query}`);
  await expect(page.getByRole('button', { name: '选择薯片', exact: true })).toBeEnabled();
}

test('SHOP-04/06: eight shelves, 96 unique pictures/prices, global guidance, keyboard and empty checkout', async ({
  page,
  appUrl,
}) => {
  await guest(page, new URL('/?shopRecognition=mock', appUrl).href);
  await page.getByRole('button', { name: '进入游戏乐园', exact: false }).click();
  await page.getByRole('button', { name: '进入拼音小卖部', exact: false }).click();
  await expect(page.getByRole('heading', { name: /拼音小卖部/ })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: '语音引导', exact: true })).toBeChecked();
  await page.getByRole('checkbox', { name: '语音引导', exact: true }).uncheck();
  const names: string[] = [];
  for (let index = 0; index < 8; index++) {
    await page.getByLabel('切换货架').getByRole('button').nth(index).click();
    await expect(page.locator('.shop-product')).toHaveCount(12);
    names.push(
      ...(await page
        .locator('.shop-product img')
        .evaluateAll((images) => images.map((image) => image.getAttribute('alt')!))),
    );
    await expect
      .poll(() =>
        page
          .locator('.shop-product img')
          .evaluateAll((images) =>
            images.every(
              (img) =>
                (img as HTMLImageElement).complete &&
                (img as HTMLImageElement).naturalWidth === 1536,
            ),
          ),
      )
      .toBe(true);
    await expect(page.locator('.shop-price-tag strong').first()).toContainText('¥');
  }
  expect(new Set(names).size).toBe(96);
  await page.getByLabel('切换货架').getByRole('button').first().focus();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('button', { name: '选择薯片', exact: true })).toBeVisible();
  expect(await page.getByRole('button', { name: '听操作提示', exact: true }).count()).toBe(0);
  for (const width of [1280, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: test.info().outputPath(`shop2-${width}.png`), fullPage: true });
  }
  await page.getByRole('button', { name: '结算购物车', exact: false }).click();
  await expect(page.getByText('结算总金额', { exact: true })).toBeVisible();
  await expect(page.locator('.shop-total strong')).toHaveText('¥0.00');
  await page.getByRole('button', { name: '休息，回游戏乐园', exact: false }).click();
  await page.getByRole('button', { name: '回到学习', exact: false }).click();
  await expect(page.getByRole('checkbox', { name: '语音引导', exact: true })).not.toBeChecked();
});

for (const mode of [
  'matched',
  'growing',
  'retry',
  'uncertain',
  'unavailable',
  'exception',
  'stale',
] as const) {
  test(`SHOP-05: automatic live capture and controlled ${mode}`, async ({
    page,
    devUrl,
    browserName,
    context,
  }) => {
    test.skip(
      browserName !== 'chromium',
      'Chromium synthetic microphone exercises capture; controlled matcher is not accuracy evidence.',
    );
    await context.grantPermissions(['microphone']);
    await openHarness(page, devUrl, `result=${mode}`);
    const before = Date.now();
    await page.getByRole('button', { name: '选择薯片', exact: true }).focus();
    await page.keyboard.press('Enter');
    await expect(page.locator('.shop-target')).toHaveText('a');
    await expect(page.locator('.shop-target')).toHaveCSS('font-family', /Andika Pinyin/);
    await expect(page.getByRole('button', { name: '完成录音', exact: false })).toHaveCount(0);
    if (mode === 'matched' || mode === 'growing') {
      await expect(page.getByLabel('我的购物车').locator('li')).toHaveCount(1, { timeout: 6000 });
      expect(Date.now() - before).toBeLessThan(5000);
      await expect(page.getByRole('button', { name: '选择薯片', exact: true })).toBeDisabled();
      if (mode === 'growing') {
        const sizes = await page.evaluate(
          () => (window as unknown as { __shopProbe: { sizes: number[] } }).__shopProbe.sizes,
        );
        expect(sizes.length).toBe(3);
        expect(sizes[1]!).toBeGreaterThan(sizes[0]!);
        expect(sizes[2]!).toBeGreaterThan(sizes[1]!);
      }
    } else {
      await expect(page.locator('.shop-feedback')).toContainText(
        mode === 'retry' ? '没有匹配' : mode === 'uncertain' ? '等待结束' : '暂不可用',
        { timeout: 6500 },
      );
      await expect(page.getByLabel('我的购物车').locator('li')).toHaveCount(0);
      await expect(page.getByRole('button', { name: '再读一次', exact: false })).toBeEnabled();
    }
  });
}

test('SHOP-05/06: six automatic additions and exact decorative checkout total', async ({
  page,
  devUrl,
  browserName,
  context,
}) => {
  test.skip(browserName !== 'chromium', 'Requires synthetic Chromium microphone.');
  await context.grantPermissions(['microphone']);
  await openHarness(page, devUrl, 'evidence=mock');
  await expect(page.getByText('开发模拟演示', { exact: true })).toBeVisible();
  const goods = page.locator('.shop-product');
  for (let i = 0; i < 6; i++) {
    await goods.nth(i).click();
    await expect(page.getByLabel('我的购物车').locator('li')).toHaveCount(i + 1, { timeout: 6000 });
  }
  await expect(goods.nth(6)).toBeDisabled();
  await expect(page.locator('.shop-total strong')).toHaveText('¥30.00');
  await page.getByRole('button', { name: '结算购物车', exact: false }).click();
  await expect(page.getByText('结算总金额', { exact: true })).toBeVisible();
  await expect(page.locator('.shop-total strong')).toHaveText('¥30.00');
  await expect(page.getByText('模拟购物清单', { exact: true })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath('shop2-checkout.png'), fullPage: true });
});

test('SHOP-05: switching goods/shelves and pause invalidate a slow response; five seconds aborts inference', async ({
  page,
  devUrl,
  browserName,
  context,
}) => {
  test.skip(browserName !== 'chromium', 'Requires synthetic Chromium microphone.');
  await context.grantPermissions(['microphone']);
  await openHarness(page, devUrl, 'delay=2500');
  await page.getByRole('button', { name: '选择薯片', exact: true }).click();
  await page.waitForTimeout(850);
  await page.getByRole('button', { name: '选择方便面', exact: true }).click();
  await expect(page.locator('.shop-target')).toHaveText('o');
  await page.getByLabel('切换货架').getByRole('button').nth(1).click();
  await page.waitForTimeout(3000);
  await expect(page.getByLabel('我的购物车').locator('li')).toHaveCount(0);
  await page.getByRole('button', { name: '选择牛奶', exact: true }).click();
  await page.getByRole('button', { name: '暂停', exact: false }).click();
  await expect(page.getByLabel('游戏已暂停')).toBeVisible();
  await page.waitForTimeout(3000);
  await page.getByRole('button', { name: '继续游戏', exact: true }).click();
  await expect(page.getByLabel('我的购物车').locator('li')).toHaveCount(0);
  await page.goto(`${devUrl}tests/support/shop-harness.html?delay=9000`);
  await page.getByRole('button', { name: '选择薯片', exact: true }).click();
  await expect(page.locator('.shop-feedback')).toContainText('等待结束', { timeout: 6500 });
  await page.waitForTimeout(4500);
  await expect(page.getByLabel('我的购物车').locator('li')).toHaveCount(0);
});

test('SHOP-05/06: microphone denial recovers and global feedback never speaks while recording', async ({
  page,
  devUrl,
  browserName,
  context,
}) => {
  test.skip(browserName !== 'chromium', 'Requires synthetic Chromium microphone.');
  await context.grantPermissions(['microphone']);
  await guest(page, devUrl);
  await page.addInitScript(() => {
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    let denied = false;
    navigator.mediaDevices.getUserMedia = (constraints) => {
      if (!denied) {
        denied = true;
        return Promise.reject(new DOMException('test denied', 'NotAllowedError'));
      }
      return original(constraints);
    };
  });
  await page.goto(`${devUrl}tests/support/shop-harness.html?result=uncertain`);
  await page.getByRole('button', { name: '选择薯片', exact: true }).click();
  await expect(page.locator('.shop-feedback')).toContainText('麦克风没有准备好');
  await page.getByRole('checkbox', { name: '语音引导', exact: true }).check();
  const voices: string[] = [];
  page.on('request', (r) => {
    if (r.url().includes('/voice/')) voices.push(r.url());
  });
  await page.getByRole('button', { name: '再读一次', exact: false }).click();
  await expect(page.locator('.shop-feedback')).toContainText('我在听');
  await page.waitForTimeout(1500);
  expect(voices).toHaveLength(0);
  await expect(page.locator('.shop-feedback')).toContainText('等待结束', { timeout: 6000 });
  await expect.poll(() => voices.some((url) => url.endsWith('/voice/ui-shop_timeout'))).toBe(true);
  await page.getByRole('checkbox', { name: '语音引导', exact: true }).uncheck();
  voices.length = 0;
  await page.getByRole('button', { name: '再读一次', exact: false }).click();
  await expect(page.locator('.shop-feedback')).toContainText('我在听');
  await page.getByRole('button', { name: '取消本次录音', exact: true }).click();
  await page.waitForTimeout(5500);
  expect(voices).toHaveLength(0);
});

test('SHOP-05: narrow selection brings the live target into view and cancels real microphone tracks', async ({
  page,
  devUrl,
  browserName,
  context,
}) => {
  test.skip(browserName !== 'chromium', 'Requires synthetic Chromium microphone.');
  await context.grantPermissions(['microphone']);
  await page.addInitScript(() => {
    const tracks: MediaStreamTrack[] = [];
    Object.defineProperty(window, '__shopTracks', { value: tracks });
    const original = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      const stream = await original(constraints);
      tracks.push(...stream.getTracks());
      return stream;
    };
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await openHarness(page, devUrl, 'result=uncertain');
  await page.getByRole('button', { name: '选择薯片', exact: true }).click();
  await expect(page.locator('.shop-feedback')).toContainText('我在听');
  await expect(page.locator('.shop-target')).toBeInViewport();
  await page.screenshot({ path: test.info().outputPath('shop2-live-390.png'), fullPage: true });
  await page.getByRole('button', { name: '取消本次录音', exact: true }).click();
  await expect
    .poll(() =>
      page.evaluate(() =>
        (window as unknown as { __shopTracks: MediaStreamTrack[] }).__shopTracks.every(
          (track) => track.readyState === 'ended',
        ),
      ),
    )
    .toBe(true);
  await page.waitForTimeout(5500);
  await expect(page.getByLabel('我的购物车').locator('li')).toHaveCount(0);
});
