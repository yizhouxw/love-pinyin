import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import { playScene } from '../support/scene-actions';
import { openGameSettings } from '../support/interaction';
import curriculum from '../../content/curriculum.json' with { type: 'json' };
import games from '../../content/games.json' with { type: 'json' };
test.use({ selectedPinyinSource: true });
for (const game of games.games)
  test(`REDESIGN ${game.scene}: touch journey, settings, pause and recovery`, async ({
    page,
    appUrl,
  }) => {
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.goto(appUrl);
    await page.getByRole('button', { name: '在本机生成家长配对码' }).click();
    await page.getByRole('button', { name: '连接家庭' }).click();
    await page.getByRole('button', { name: '进入游戏乐园' }).click();
    await openGameSettings(page, game.title);
    await page.getByLabel(`${game.title}难度`).selectOption('gentle');
    await page.getByLabel(`${game.title}每关题量`).selectOption('3');
    const settings = page.getByLabel(`${game.title}设置`, { exact: true });
    if (await settings.evaluate((el) => (el.parentElement as HTMLDetailsElement).open))
      await page.getByRole('button', { name: '完成', exact: true }).click();
    const created = page.waitForResponse(
      (r) => r.url().endsWith('/sessions') && r.request().method() === 'POST',
    );
    await page.getByRole('button', { name: `开始${game.title}` }).click();
    await page.getByRole('button', { name: '▶ 开始游戏', exact: true }).click();
    const session = await (await created).json();
    const stage = page.locator('.adventure-canvas');
    await expect(stage).toBeVisible();
    await expect(stage.locator('svg')).toBeVisible();
    await page.getByRole('button', { name: '游戏设置' }).click();
    await expect(page.getByRole('dialog', { name: '游戏设置' })).toBeInViewport();
    await page.keyboard.press('Escape');
    await expect(page.getByRole('button', { name: '游戏设置' })).toBeFocused();
    await page.getByRole('button', { name: 'Ⅱ 暂停', exact: true }).click();
    const frozen = await stage.getAttribute('data-world-distance');
    await page.waitForTimeout(150);
    expect(await stage.getAttribute('data-world-distance')).toBe(frozen);
    await page.getByRole('button', { name: '▶ 继续游戏', exact: true }).click();
    for (const [width, height] of [
      [390, 844],
      [844, 390],
      [1180, 820],
    ] as const) {
      await page.setViewportSize({ width, height });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page.screenshot({
        path: test.info().outputPath(`${game.scene}-${width}.png`),
        fullPage: true,
      });
    }
    await page.setViewportSize({ width: 390, height: 844 });
    await stage.evaluate((el) => el.setAttribute('data-continuity-probe', 'retained'));
    for (let i = 0; i < 3; i++) {
      await expect(page.locator('.scene-nav')).toContainText(`任务 ${i + 1} / 3`);
      const q = curriculum.exercises.find((q) => q.id === session.tasks[i].exercise.id)!;
      await playScene(page, q.answer.optionId!);
      if (i === 0) {
        await expect(page.locator('.scene-nav')).toContainText('任务 2 / 3');
        await expect(stage).toHaveAttribute('data-continuity-probe', 'retained');
        await page.reload();
        await expect(stage).toBeVisible();
      }
    }
    await expect(page.locator('.scene-nav')).toHaveCount(0, { timeout: 20000 });
    const exported = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
    expect(exported.attempts).toHaveLength(3);
    expect(
      exported.attempts.every((a: { first_try_correct: number }) => a.first_try_correct === 1),
    ).toBe(true);
    expect(errors).toEqual([]);
  });

test('ACTION-03: drag and keyboard control the aircraft, space fires a real beam', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在本机生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭' }).click();
  await page.getByRole('button', { name: '进入游戏乐园' }).click();
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/sessions') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: '开始星际投递' }).click();
  const session = await (await created).json();
  await page.getByRole('button', { name: '▶ 开始游戏', exact: true }).click();
  const stage = page.locator('.adventure-canvas');
  await expect(page.locator('button[data-option-id]').first()).toBeEnabled({ timeout: 20000 });
  await page.keyboard.down('ArrowRight');
  await page.waitForTimeout(180);
  await page.keyboard.up('ArrowRight');
  expect(Number(await stage.getAttribute('data-world-x'))).toBeGreaterThan(260);
  const q = curriculum.exercises.find((q) => q.id === session.tasks[0].exercise.id)!;
  await page.locator(`button[data-option-id="${q.answer.optionId}"]`).click();
  await stage.focus();
  await page.keyboard.press('Space');
  await expect(page.locator('.scene-nav')).toContainText('任务 2 /', { timeout: 20000 });
  await page.screenshot({ path: test.info().outputPath('space-action.png'), fullPage: true });
  const result = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
  expect(result.attempts).toHaveLength(1);
  expect(result.attempts[0].first_try_correct).toBe(1);
});
