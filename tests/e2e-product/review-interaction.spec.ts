import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import curriculum from '../../content/curriculum.json' with { type: 'json' };
import { playScene } from '../support/scene-actions';
import catalog from '../../content/games.json' with { type: 'json' };

test.use({ selectedPinyinSource: true });

test('in-app return consumes the history entry; a direct link returns to home', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在本机生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭' }).click();
  const home = page.getByRole('button', { name: '进入游戏乐园' });
  await home.click();
  const games = page.getByRole('main', { name: '拼音游戏乐园' });
  await expect(games).toBeVisible();
  await games.getByRole('button', { name: /回到学习/ }).click();
  await expect(home).toBeFocused();
  await page.goForward();
  await expect(games).toBeVisible();
  const direct = await page.context().newPage();
  await direct.goto(appUrl + '#daily-reading');
  const daily = direct.getByRole('main', { name: '天天练拼音', exact: true });
  await expect(daily).toBeVisible();
  await daily.getByRole('button', { name: /返回小岛/ }).click();
  await expect(direct.getByRole('button', { name: '进入游戏乐园' })).toBeVisible();
  expect(new URL(direct.url()).hash).toBe('');
});

for (const game of catalog.games) {
  test(`${game.title}: changing Reduce Motion preserves the question and permits scoring`, async ({
    page,
    appUrl,
  }) => {
    await page.goto(appUrl);
    await page.getByRole('button', { name: '在本机生成家长配对码' }).click();
    await page.getByRole('button', { name: '连接家庭' }).click();
    await page.getByRole('button', { name: '进入游戏乐园' }).click();
    const created = page.waitForResponse(
      (response) => response.url().endsWith('/sessions') && response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: `开始${game.title}` }).click();
    await page.getByRole('button', { name: '▶ 开始游戏', exact: true }).click();
    const round = await (await created).json();
    const exercise = curriculum.exercises.find((item) => item.id === round.tasks[0].exercise.id)!;
    const option = exercise.options.find((item) => item.id === exercise.answer.optionId)!;
    const stage = page.locator('.adventure-canvas');
    await expect(stage).toBeVisible();
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await expect(stage).toBeVisible();
    await expect(page.locator('.scene-nav')).toContainText('任务 1 /');
    await expect(page.locator('.adventure-canvas svg')).toBeVisible();
    await expect(page.locator('button[data-option-id]').first()).toBeEnabled({ timeout: 20000 });
    // System Reduce Motion must never stop game physics or change answer mechanics.
    if (game.scene === 'runner') {
      const distance = Number(await stage.getAttribute('data-world-distance'));
      await expect
        .poll(async () => Number(await stage.getAttribute('data-world-distance')))
        .toBeGreaterThan(distance + 10);
    }
    await page.screenshot({
      path: test.info().outputPath(`still-${game.scene}.png`),
      fullPage: true,
    });
    await playScene(page, option.id);
    await expect(page.locator('.scene-nav')).toContainText('任务 2 /', { timeout: 20000 });
  });
}

for (const game of catalog.games) {
  test(`${game.title}: scene touch controls preserve sound and pause protection`, async ({
    page,
    appUrl,
  }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(appUrl);
    await page.getByRole('button', { name: '在本机生成家长配对码' }).click();
    await page.getByRole('button', { name: '连接家庭' }).click();
    await page.getByRole('button', { name: '进入游戏乐园' }).click();
    await page.getByRole('button', { name: `开始${game.title}` }).click();
    await page.getByRole('button', { name: '▶ 开始游戏', exact: true }).click();
    const stage = page.locator('.adventure-canvas');
    const character = page.locator('button[data-option-id]').first();
    await expect(character).toBeEnabled({ timeout: 20000 });
    await page.getByRole('button', { name: '听拼音', exact: true }).click();
    await expect(character).toBeDisabled();
    await expect(character).toBeEnabled({ timeout: 20000 });
    await page.getByRole('button', { name: 'Ⅱ 暂停', exact: true }).click();
    await expect(character).toBeDisabled();
    const position = await stage.getAttribute('data-world-x');
    await page.keyboard.press('ArrowLeft');
    expect(await stage.getAttribute('data-world-x')).toBe(position);
  });
}
