import { expect } from '@playwright/test';
import { execFileSync } from 'node:child_process';
import { test } from '../support/real-server';

test('ACCESS-01: guest learns with real voice, reloads, changes lesson and clears without household writes', async ({
  page,
  appUrl,
  dataDirectory,
  context,
}) => {
  test.setTimeout(90_000);
  const household = () =>
    execFileSync(
      'uv',
      [
        'run',
        '--locked',
        'python',
        '-c',
        `
import json
from server.storage import connect
with connect() as db:
    print(json.dumps(list(db.iterdump())))
`,
      ],
      { env: { ...process.env, LOVE_PINYIN_DATA_DIR: dataDirectory }, encoding: 'utf8' },
    );
  const before = household();
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(appUrl);
  await expect(page.getByRole('heading', { name: '没有配对码？' })).toBeVisible();
  await expect(page.getByRole('button', { name: '在 Mac 上生成家长配对码' })).toBeVisible();
  await page.screenshot({ path: test.info().outputPath('pairing-home.png'), fullPage: true });
  await page.getByRole('button', { name: '访客体验' }).click();
  await expect(page.getByLabel('访客模式')).toBeVisible();
  expect((await context.cookies()).filter((cookie) => cookie.name.startsWith('lp_'))).toEqual([]);
  const voice = page.waitForResponse(
    (response) =>
      response.url().includes('/guest/voice/prompt-') && [200, 206].includes(response.status()),
  );
  await page.getByRole('button', { name: '开始今天的练习' }).click();
  expect((await voice).headers()['content-type']).toMatch(/^audio\//);
  const choice = page.getByRole('group', { name: '选择答案' }).getByRole('button').first();
  await expect(choice).toBeEnabled({ timeout: 15_000 });
  // A failed network request must not advance/corrupt the cached record.
  let interrupted = false;
  await page.route('**/guest/operate', async (route) => {
    const operation = route.request().postDataJSON();
    if (operation.path.endsWith('/answer') && !interrupted) {
      interrupted = true;
      await route.abort();
    } else await route.continue();
  });
  await choice.click();
  await expect(page.getByRole('alert')).toContainText('暂时无法连接');
  await choice.click();
  await expect(page.locator('.feedback')).toBeVisible();
  await page.reload();
  await expect(page.getByText('第 2 / 6 关')).toBeVisible();
  await page.getByRole('button', { name: '退出练习' }).click();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await expect(page.getByText(/1 次临时练习记录/)).toBeVisible();
  await page.screenshot({ path: test.info().outputPath('guest-progress.png'), fullPage: true });
  await expect(page.getByRole('button', { name: '导出家庭数据' })).toHaveCount(0);
  await page.getByLabel('当前学习课', { exact: true }).selectOption('lesson-02');
  await page.getByRole('button', { name: '应用到访客练习' }).click();
  await expect(page.getByText('当前练习：第 2 课')).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await expect(page.getByLabel('当前学习课', { exact: true })).toHaveValue('lesson-02');
  await expect(page.getByText(/1 次临时练习记录/)).toBeVisible();
  expect(household()).toBe(before);
  await page
    .getByLabel('访客模式', { exact: true })
    .getByRole('button', { name: '清除并退出访客' })
    .click();
  await expect(page.getByRole('button', { name: '访客体验' })).toBeVisible();
  expect(await page.evaluate(() => sessionStorage.getItem('lp.guest.v1'))).toBeNull();
  await page.getByRole('button', { name: '访客体验' }).click();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await expect(page.getByText(/0 次临时练习记录/)).toBeVisible();
  await expect(page.getByLabel('当前学习课', { exact: true })).toHaveValue('lesson-01');
  expect(household()).toBe(before);
  expect(errors).toEqual([]);
});

test('ACCESS-01: expired pairing cookie still shows generation and generated code is filled', async ({
  page,
  appUrl,
  context,
}) => {
  await context.addCookies([{ name: 'lp_session', value: 'expired', url: appUrl }]);
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  await expect(page.getByLabel('家长配对码')).toHaveValue(/^[A-Z2-9]{8}$/);
  await page.getByRole('button', { name: '连接家庭' }).click();
  await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeVisible();
});

test('ACCESS-02: guest mode stays visible and local pairing management connects the real household', async ({
  page,
  appUrl,
  context,
}) => {
  await page.setViewportSize({ width: 768, height: 1024 });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验' }).click();
  const banner = page.getByLabel('访客模式', { exact: true });
  await expect(banner).toContainText('当前：访客模式');
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  const management = page.getByRole('region', { name: '配对码管理' });
  await expect(management.getByRole('button', { name: '清除并退出访客' })).toBeVisible();
  await management.getByLabel('家长配对码').fill('ZZZZZZZZ');
  const before = await page.evaluate(() => sessionStorage.getItem('lp.guest.v1'));
  await management.getByRole('button', { name: '连接家庭' }).click();
  await expect(management.getByRole('alert')).toContainText('已过期');
  expect(await page.evaluate(() => sessionStorage.getItem('lp.guest.v1'))).toBe(before);
  await management.getByRole('button', { name: '生成配对码', exact: true }).click();
  await expect(management.getByLabel('家长配对码')).toHaveValue(/^[A-Z2-9]{8}$/);
  await expect(management.getByRole('status')).toContainText('5 分钟内一次有效');
  await page.evaluate(() => window.scrollTo(0, document.body.scrollHeight));
  await expect(banner.getByRole('button', { name: '清除并退出访客' })).toBeInViewport();
  await page.screenshot({
    path: test.info().outputPath('guest-pairing-ipad-viewport.png'),
    fullPage: true,
  });
  await management.getByRole('button', { name: '连接家庭' }).click();
  await expect(page.getByLabel('家庭模式', { exact: true })).toContainText('家长设备');
  await expect(page.getByLabel('访客模式', { exact: true })).toHaveCount(0);
  expect(await page.evaluate(() => sessionStorage.getItem('lp.guest.v1'))).toBeNull();
  expect((await context.cookies()).some((cookie) => cookie.name === 'lp_session')).toBe(true);
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await page.getByRole('button', { name: '生成配对码', exact: true }).click();
  const code = await management.locator('.pair-code').innerText();
  expect(code).toMatch(/[A-Z2-9]{8}/);
});

test('ACCESS-02: local paired learning device can generate a code from parent management', async ({
  page,
  appUrl,
  browser,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭' }).click();
  await expect(page.getByLabel('家庭模式', { exact: true })).toContainText('家长设备');
  const childContext = await browser.newContext();
  try {
    const child = await childContext.newPage();
    await child.goto(appUrl);
    await child.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
    await child.getByRole('button', { name: '连接家庭' }).click();
    await expect(child.getByLabel('家庭模式', { exact: true })).toContainText('学习设备');
    await child.getByRole('button', { name: '家长管理' }).click();
    await child.getByRole('button', { name: '我是家长，继续' }).click();
    await child.getByRole('button', { name: '生成配对码', exact: true }).click();
    await expect(
      child.getByRole('region', { name: '配对码管理' }).getByRole('status'),
    ).toContainText('5 分钟内一次有效');
  } finally {
    await childContext.close();
  }
});
