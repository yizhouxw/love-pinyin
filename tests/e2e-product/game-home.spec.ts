import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import { openGameSettings } from '../support/interaction';
import games from '../../content/games.json' with { type: 'json' };

test.use({ selectedPinyinSource: true });

test('HOME-01/02: compact home, independent settings, keyboard, saved choices and real start', async ({
  page,
  appUrl,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.setViewportSize({ width: 1280, height: 1100 });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭' }).click();
  await page.getByRole('button', { name: '进入游戏乐园' }).click();
  const forest = page.locator('.game-sound');
  const boat = page.locator('.game-tone');
  await expect(page.getByRole('button', { name: '开始森林跑酷' })).toBeEnabled();
  await expect(page.locator('.game-card-settings[open]')).toHaveCount(0);
  await expect(page.locator('.game-home-details details[open]')).toHaveCount(0);
  for (const game of games.games) {
    await expect(page.getByRole('button', { name: `开始${game.title}` })).toBeInViewport();
    await expect(page.getByLabel(`${game.title}关卡`)).toBeVisible();
    await expect(page.getByLabel(`${game.title}每关题量`)).toBeVisible();
    expect((await page.locator(`.game-${game.id}`).boundingBox())!.height).toBeLessThan(320);
  }
  expect((await forest.boundingBox())!.y).toBe((await boat.boundingBox())!.y);
  const boatHeight = (await boat.boundingBox())!.height;
  const route = await page.getByLabel('森林跑酷关卡').inputValue();
  const summary = page.getByLabel('森林跑酷设置', { exact: true });
  await summary.focus();
  await page.keyboard.press('Enter');
  await expect(page.getByLabel('森林跑酷难度')).toBeVisible();
  expect((await boat.boundingBox())!.height).toBe(boatHeight);
  await page.getByLabel('森林跑酷难度').selectOption('challenge');
  await expect(page.getByLabel('森林跑酷关卡')).toHaveValue(route);
  await page.getByLabel('森林跑酷速度').selectOption('fast');
  await page.getByLabel('森林跑酷每关题量').selectOption('3');
  await page.getByLabel('森林跑酷关卡').selectOption('runner-02');
  await expect(summary).toContainText('挑战');
  await expect(summary).toContainText('快速');
  await expect(page.getByRole('button', { name: '听关卡故事：蘑菇小径' })).toBeVisible();
  await summary.focus();
  await page.keyboard.press('Space');
  await expect(page.getByLabel('森林跑酷难度')).not.toBeVisible();
  await page.getByRole('button', { name: '回到学习' }).click();
  await page.getByRole('button', { name: '进入游戏乐园' }).click();
  await openGameSettings(page, '森林跑酷');
  await expect(page.getByLabel('森林跑酷难度')).toHaveValue('challenge');
  await expect(page.getByLabel('森林跑酷速度')).toHaveValue('fast');
  await expect(page.getByLabel('森林跑酷每关题量')).toHaveValue('3');
  await page.getByLabel('森林跑酷关卡').selectOption('runner-02');
  await page.getByRole('button', { name: '回到学习' }).click();
  await page.getByRole('button', { name: '进入游戏乐园' }).click();
  for (const width of [1280, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: test.info().outputPath(`home-${width}.png`), fullPage: true });
    const targets = page
      .locator('.game-zone')
      .locator('button:visible,select:visible,summary:visible');
    for (let i = 0; i < (await targets.count()); i++)
      expect((await targets.nth(i).boundingBox())!.height).toBeGreaterThanOrEqual(48);
  }
  await page.evaluate(() => (document.documentElement.style.fontSize = '200%'));
  await openGameSettings(page, '森林跑酷');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.screenshot({ path: test.info().outputPath('home-320-text-200.png'), fullPage: true });
  await page.locator('.game-home-info > summary').click();
  await expect(page.locator('.game-home-info')).toContainText('连续休息 10 分钟');
  await page.locator('.game-home-evidence > summary').click();
  await expect(page.getByLabel('游戏学习效果')).toBeVisible();
  await page.evaluate(() => (document.documentElement.style.fontSize = ''));
  await page.getByLabel('森林跑酷关卡').selectOption('runner-02');
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/sessions') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: '开始森林跑酷' }).click();
  const session = await (await created).json();
  expect(session.gameRun.level.id).toBe('runner-02');
  expect(session.tasks).toHaveLength(3);
  expect(session.gameSettings.level).toBe('challenge');
  expect(session.gameSettings.speed).toBe('fast');
  await expect(page.locator('.scene-stage')).toBeVisible();
  await page.getByRole('button', { name: '保存并退出游戏' }).click();
  await expect(page.getByRole('heading', { name: '拼音游戏乐园' })).toBeVisible();
  expect(errors).toEqual([]);
});

test('HOME-02: loading and failed real clock status disable starts and retry recovers', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭' }).click();
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  await page.route('**/api/v1/games', async (route) => {
    await gate;
    await route.abort('failed').catch(() => {});
  });
  await page.getByRole('button', { name: '进入游戏乐园' }).click();
  await expect(page.getByLabel('游戏时长约定')).toContainText('正在确认');
  for (const game of games.games)
    await expect(page.getByRole('button', { name: `开始${game.title}` })).toBeDisabled();
  await expect(page.getByRole('button', { name: '进入拼音小卖部' })).toBeDisabled();
  await expect(page.getByRole('alert')).toContainText('暂时无法连接', { timeout: 10000 });
  release();
  await page.unroute('**/api/v1/games');
  await page.getByRole('button', { name: '刷新可玩时间' }).click();
  await expect(page.getByRole('alert')).toHaveCount(0);
  for (const game of games.games)
    await expect(page.getByRole('button', { name: `开始${game.title}` })).toBeEnabled();
  await page.getByRole('button', { name: '进入拼音小卖部' }).click();
  await expect(page.getByRole('heading', { name: /^拼音小卖部/ })).toBeVisible();
});
