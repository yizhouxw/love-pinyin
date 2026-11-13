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
    for (let i = 0; i < 3; i++) {
      await expect(page.locator('.scene-nav')).toContainText(`任务 ${i + 1} / 3`);
      const q = curriculum.exercises.find((q) => q.id === session.tasks[i].exercise.id)!;
      await playScene(page, q.answer.optionId!);
      if (i === 0) {
        await expect(page.locator('.scene-nav')).toContainText('任务 2 / 3');
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

test('REDESIGN-04: a short finger pull previews and delivers a parcel; cancel never fires', async ({
  page,
  appUrl,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在本机生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭' }).click();
  await page.getByRole('button', { name: '进入游戏乐园' }).click();
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/sessions') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: '开始星际投递' }).click();
  const session = await (await created).json();
  const q = curriculum.exercises.find((q) => q.id === session.tasks[0].exercise.id)!;
  const options = session.tasks[0].exercise.options as { id: string }[];
  const index = options.findIndex((o) => o.id === q.answer.optionId);
  const stage = page.locator('.adventure-canvas');
  await expect(page.locator('button[data-option-id]').first()).toBeEnabled({ timeout: 20000 });
  const box = (await stage.boundingBox())!;
  const start = { x: box.x + box.width * 0.5, y: box.y + box.height * 0.55 };
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(start.x + 20, start.y + 20);
  // A vertical trajectory has zero geometric width but a visible SVG stroke.
  await expect(stage.locator('polyline')).toHaveAttribute('stroke', '#ffe7a3');
  expect(
    await stage
      .locator('polyline')
      .evaluate((line) => (line as SVGPolylineElement).getBBox().height),
  ).toBeGreaterThan(100);
  await stage.dispatchEvent('pointercancel', { pointerId: 1 });
  await page.mouse.up();
  await expect(stage.locator('polyline')).toHaveCount(0);
  expect(await stage.getAttribute('data-world-hit')).toBe('');
  const x = 60 + (index * 360) / Math.max(1, options.length - 1),
    y = 80 + (index % 2) * 38;
  const vx = (x - 240) / 1.5,
    vy = (y - 350 - 120 * 1.5 * 1.5) / 1.5;
  await page.mouse.move(start.x, start.y);
  await page.mouse.down();
  await page.mouse.move(
    start.x - (vx / 3 / 480) * box.width,
    start.y + ((-250 - vy) / 5 / 400) * box.height,
    { steps: 8 },
  );
  // A vertical trajectory has zero geometric width but a visible SVG stroke.
  await expect(stage.locator('polyline')).toHaveAttribute('stroke', '#ffe7a3');
  expect(
    await stage
      .locator('polyline')
      .evaluate((line) => (line as SVGPolylineElement).getBBox().height),
  ).toBeGreaterThan(100);
  await page.mouse.up();
  await expect(page.locator('.scene-nav')).toContainText('任务 2 /', { timeout: 20000 });
  const result = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
  expect(result.attempts).toHaveLength(1);
  expect(result.attempts[0].first_try_correct).toBe(1);
});
