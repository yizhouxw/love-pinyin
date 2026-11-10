import { spawn } from 'node:child_process';
import { mkdir, readFile, symlink } from 'node:fs/promises';
import { join } from 'node:path';
import standardAudio from '../../resources/audio/ios-standard/manifest.json' with { type: 'json' };
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
  await expect(page.getByText('模拟识别', { exact: true })).toBeVisible();
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
  await expect(page.getByText('结算总金额', { exact: true })).toBeVisible();
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
  await page.getByRole('button', { name: '切换到本地识别' }).click();
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

test('SHOP-17: listening to the correct sound cancels active capture on a narrow screen', async ({
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
  const audio = page.waitForResponse(
    (response) => response.url().includes('/audio/audio-final-a') && response.ok(),
  );
  await page.getByRole('button', { name: '听正确读音', exact: true }).click();
  await audio;
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

test('SHOP-16/17: short sentences, optional Chinese text and replay without recognition', async ({
  page,
  appUrl,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'mediaDevices', { value: undefined });
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await guest(page, appUrl);
  await page.getByRole('button', { name: '进入游戏乐园' }).click();
  await page.getByRole('button', { name: '进入拼音小卖部' }).click();
  await page.getByRole('checkbox', { name: '语音引导', exact: true }).uncheck();
  await page.getByRole('button', { name: '选择薯片', exact: true }).click();
  const sound = page.getByRole('button', { name: '听正确读音', exact: true });
  await expect(sound).toBeEnabled();
  const sentenceMode = page.getByRole('button', { name: '句子拼读', exact: true });
  await sentenceMode.click();
  await expect(sentenceMode).toHaveAttribute('aria-pressed', 'true');
  const pinyin = page.getByRole('heading', { name: 'bà ba hē chá.', exact: true });
  const hanzi = page.getByText('爸爸喝茶。', { exact: true });
  await expect(pinyin).toBeVisible();
  await expect(hanzi).toBeVisible();
  await page.getByRole('button', { name: '隐藏汉字', exact: true }).click();
  await expect(hanzi).toHaveCount(0);
  await expect(pinyin).toBeVisible();
  const audio = page.waitForResponse(
    (response) => response.url().includes('/voice/ui-shop-sentence-tea') && response.ok(),
  );
  await sound.click();
  await audio;
  await expect(sound).toHaveAttribute('aria-pressed', 'true');
  await expect(sound).toHaveAttribute('aria-pressed', 'false');
  await page.getByRole('button', { name: '显示汉字', exact: true }).click();
  await expect(hanzi).toBeVisible();
  const basket = page.getByLabel('我的购物车').locator('li');
  await expect(basket).toHaveCount(0);
  await page.getByRole('button', { name: '读完了，加入购物车' }).click();
  await expect(basket).toHaveText(/薯片/);
  await expect(sound).toBeEnabled();
  await page.getByRole('button', { name: '音节拼读', exact: true }).click();
  await expect(basket).toHaveCount(1);
  await page.locator('.shop-product').nth(1).click();
  await expect(page.locator('.shop-target')).toHaveText('o');
  await expect(sound).toBeEnabled();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(390);
});

test('SHOP-10: manual confirmation requires an explicit action for each item', async ({
  page,
  appUrl,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'mediaDevices', { value: undefined, configurable: true });
    Object.defineProperty(window.crypto, 'randomUUID', { value: undefined, configurable: true });
  });
  await guest(page, appUrl);
  await page.getByRole('button', { name: '进入游戏乐园', exact: false }).click();
  await page.getByRole('button', { name: '进入拼音小卖部', exact: false }).click();
  await expect(page.getByText('人工确认', { exact: true })).toBeVisible();
  expect(await page.evaluate(() => navigator.mediaDevices)).toBeUndefined();
  expect(await page.evaluate(() => typeof window.crypto.randomUUID)).toBe('undefined');
  const goods = page.locator('.shop-product');
  for (let i = 0; i < 6; i++) {
    await goods.nth(i).click();
    await expect(page.getByLabel('我的购物车').locator('li')).toHaveCount(i);
    await page.getByRole('button', { name: '读完了，加入购物车' }).click();
    await expect(page.getByLabel('我的购物车').locator('li')).toHaveCount(i + 1);
    await expect(page.locator('.shop-feedback')).toContainText('已确认读完');
  }
  await expect(goods.nth(6)).toBeDisabled();
  await page.getByRole('button', { name: '结算购物车', exact: false }).click();
  await expect(page.getByText('结算总金额', { exact: true })).toBeVisible();
  await expect(page.locator('.shop-total strong')).toHaveText('¥30.00');
  await page.screenshot({
    path: test.info().outputPath('shop3-production-checkout.png'),
    fullPage: true,
  });
});

test('SHOP-10: audible manual instructions and explicit confirmation', async ({ page, appUrl }) => {
  await guest(page, appUrl);
  await page.getByRole('button', { name: '进入游戏乐园', exact: false }).click();
  const intro = page.waitForResponse(
    (response) => response.url().includes('/voice/ui-shop_manual_welcome') && response.ok(),
  );
  await page.getByRole('button', { name: '听小卖部怎么玩', exact: true }).click();
  await intro;
  await page.getByRole('button', { name: '进入拼音小卖部', exact: false }).click();
  const feedback = page.waitForResponse(
    (response) => response.url().includes('/voice/ui-shop_manual_added') && response.ok(),
  );
  await page.getByRole('button', { name: '选择薯片', exact: true }).click();
  await expect(page.getByLabel('我的购物车').locator('li')).toHaveCount(0);
  await page.getByRole('button', { name: '读完了，加入购物车' }).click();
  await expect(page.getByLabel('我的购物车').locator('li')).toHaveCount(1);
  await feedback;
});

test('SHOP-09/10: installed Qwen matches licensed audio in the production shop', async ({
  page,
  appUrl,
  dataDirectory,
}) => {
  const modelDir = process.env.LOVE_PINYIN_TEST_QWEN_DIR;
  test.skip(!modelDir, 'Run with an explicit verified local Qwen model directory.');
  const modelParent = join(dataDirectory, 'models');
  await mkdir(modelParent);
  await symlink(modelDir!, join(modelParent, 'qwen3-asr-0.6b'));
  const audio = await readFile(
    join('resources/audio/ios-standard', standardAudio.clips['audio-final-a'].file),
  );
  await page.addInitScript(
    (bytes) => {
      Object.defineProperty(navigator, 'mediaDevices', {
        configurable: true,
        value: {
          getUserMedia: async () => {
            const context = new AudioContext();
            void context.resume().catch(() => undefined);
            const destination = context.createMediaStreamDestination();
            const source = context.createBufferSource();
            source.buffer = await context.decodeAudioData(new Uint8Array(bytes).buffer);
            source.connect(destination);
            source.start(context.currentTime + 0.2);
            return destination.stream;
          },
        },
      });
    },
    [...audio],
  );
  await guest(page, appUrl);
  await page.getByRole('button', { name: '进入游戏乐园', exact: false }).click();
  await page.getByRole('button', { name: '进入拼音小卖部', exact: false }).click();
  await expect(page.getByText('本地语音识别', { exact: true })).toBeVisible();
  await page.getByRole('checkbox', { name: '语音引导', exact: true }).uncheck();
  const match = page.waitForResponse(async (response) => {
    if (!response.url().endsWith('/assess') || !response.ok()) return false;
    return (await response.json()).match.status === 'matched';
  });
  await page.getByRole('button', { name: '选择薯片' }).click();
  await expect(page.getByLabel('我的购物车').locator('li')).toHaveCount(1, { timeout: 7000 });
  expect((await (await match).json()).saved).toBe(false);
});
