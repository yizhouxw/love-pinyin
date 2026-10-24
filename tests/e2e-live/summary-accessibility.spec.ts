import { expect, type Page } from '@playwright/test';
import { test } from '../support/real-server';

async function finishSixTasks(page: Page, appUrl: string) {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭', exact: true }).click();
  await page.getByRole('button', { name: '开始今天的练习', exact: true }).click();
  for (let index = 1; index <= 6; index++) {
    await expect(page.locator('.play-nav strong')).toHaveText(`第 ${index} / 6 关`);
    await page.getByRole('button', { name: '↷ 先跳过这题', exact: true }).click();
  }
  await expect(page.getByLabel('本次练习小结')).toContainText('跳过：6 题');
}

test('SUMMARY-01A: summary controls remain large and usable with narrow enlarged text', async ({
  page,
  appUrl,
}) => {
  const sound = page.waitForResponse((response) => response.url().endsWith('/voice/ui-summary'));
  await finishSixTasks(page, appUrl);
  expect((await sound).headers()['content-type']).toMatch(/^audio\//);
  await page.getByRole('button', { name: '停止听小结', exact: true }).press('Enter');
  await expect(page.getByRole('button', { name: '听小结', exact: true })).toBeVisible();
  const back = page.getByRole('button', { name: '回到小岛', exact: true });
  const normalSize = await back.boundingBox();
  expect(normalSize!.height).toBeGreaterThanOrEqual(48);
  expect(normalSize!.width).toBeGreaterThanOrEqual(48);
  await page.setViewportSize({ width: 320, height: 844 });
  await page.evaluate(() => {
    const elements = Array.from(document.querySelectorAll<HTMLElement>('h1, p, button, li'));
    const sizes = elements.map((element) => parseFloat(getComputedStyle(element).fontSize));
    elements.forEach((element, index) => (element.style.fontSize = `${sizes[index]! * 2}px`));
  });
  const layout = await page.evaluate(() => ({
    width: document.documentElement.scrollWidth,
    viewport: document.documentElement.clientWidth,
    controls: Array.from(document.querySelectorAll('main button')).map((button) => {
      const { width, height } = button.getBoundingClientRect();
      return { width, height };
    }),
  }));
  expect(layout.width).toBeLessThanOrEqual(layout.viewport);
  expect(layout.controls).toHaveLength(2);
  expect(layout.controls.every(({ width, height }) => width >= 48 && height >= 48)).toBe(true);
  await page.getByRole('button', { name: '听小结', exact: true }).press('Enter');
  await expect(page.getByRole('button', { name: '停止听小结', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '停止听小结', exact: true }).press('Enter');
  await page.screenshot({
    path: test.info().outputPath('summary-320-large-text.png'),
    fullPage: true,
  });
  await back.press('Enter');
  await expect(page.getByRole('button', { name: '开始今天的练习', exact: true })).toBeVisible();
});

test('SUMMARY-01B: real server failure on finish is visible and retry credits one round', async ({
  page,
  appUrl,
  serverControl,
}) => {
  await finishSixTasks(page, appUrl);
  const before = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
  const back = page.getByRole('button', { name: '回到小岛', exact: true });
  await serverControl.stop();
  await back.press('Enter');
  await expect(page.locator('.error-notice[role=alert]')).toContainText('本次操作尚未确认');
  await expect(page.getByLabel('本次练习小结')).toContainText('跳过：6 题');
  await expect(back).toBeEnabled();
  await serverControl.start();
  await page.getByRole('button', { name: '重新连接并恢复', exact: true }).press('Enter');
  await expect(page.locator('.error-notice[role=alert]')).toHaveCount(0);
  await expect(back).toBeEnabled();
  await expect(page.getByLabel('本次练习小结')).toContainText('跳过：6 题');
  await back.press('Enter');
  await expect(page.getByRole('button', { name: '开始今天的练习', exact: true })).toBeVisible();
  const after = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
  expect(before.attempts).toHaveLength(0);
  expect(before.skippedInstances).toHaveLength(6);
  expect(after.attempts).toEqual(before.attempts);
  expect(after.skippedInstances).toEqual(before.skippedInstances);
  expect(after.sessions).toHaveLength(1);
  expect(after.sessions[0].status).toBe('finished');
  const progress = await (await page.request.get(`${appUrl}/api/v1/profiles/progress`)).json();
  expect(progress.completedSessions).toBe(1);
  await page.reload();
  await expect(page.getByRole('button', { name: '开始今天的练习', exact: true })).toBeVisible();
});

test('SUMMARY-01D: exit waits for the real answer progress refresh before another round', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭', exact: true }).click();
  await page.getByRole('button', { name: '开始今天的练习', exact: true }).click();
  const choice = page.getByRole('group', { name: '选择答案' }).getByRole('button').first();
  await expect(choice).toBeEnabled({ timeout: 15_000 });
  let release!: () => void;
  let observed!: () => void;
  const gate = new Promise<void>((resolve) => (release = resolve));
  const waiting = new Promise<void>((resolve) => (observed = resolve));
  let holdNext = true;
  await page.route('**/api/v1/profiles/progress', async (route) => {
    if (holdNext) {
      holdNext = false;
      observed();
      await gate;
    }
    await route.continue();
  });
  let finishes = 0;
  page.on('request', (request) => {
    if (request.url().endsWith('/finish')) finishes++;
  });
  try {
    await choice.press('Enter');
    await waiting;
    await expect(page.locator('.feedback')).toBeVisible();
    const exit = page.getByRole('button', { name: '退出练习', exact: true });
    await expect(exit).toBeDisabled();
    await exit.press('Enter');
    expect(finishes).toBe(0);
    release();
    await expect(exit).toBeEnabled();
    await exit.click();
    const start = page.getByRole('button', { name: '开始今天的练习', exact: true });
    await expect(start).toBeEnabled();
    await start.click();
    await expect(choice).toBeEnabled({ timeout: 15_000 });
    expect(finishes).toBe(1);
    const backup = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
    expect(backup.attempts).toHaveLength(1);
    expect(backup.sessions).toHaveLength(2);
    expect(
      backup.sessions.filter((session: { status: string }) => session.status === 'active'),
    ).toHaveLength(1);
  } finally {
    release();
  }
});
