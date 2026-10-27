import { openGameSettings } from '../support/interaction';
import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import { playScene } from '../support/scene-actions';
import curriculum from '../../content/curriculum.json' with { type: 'json' };
import catalog from '../../content/games.json' with { type: 'json' };

test.use({ selectedPinyinSource: true });
for (const game of catalog.games) {
  test(`PLAY ${game.scene}: immediate targets, in-game settings, inline enlargement and complete journey`, async ({
    page,
    appUrl,
  }) => {
    test.setTimeout(180000);
    const errors: string[] = [];
    page.on('pageerror', (e) => errors.push(e.message));
    await page.goto(appUrl);
    await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
    await page.getByRole('button', { name: '连接家庭' }).click();
    await page.getByRole('button', { name: '进入游戏乐园' }).click();
    await expect(page.getByLabel(`${game.title}每关题量`)).toHaveValue('6');
    const count = game.id === 'sound' ? 6 : 3;
    await page.getByLabel(`${game.title}每关题量`).selectOption(String(count));
    await openGameSettings(page, game.title);
    await page.getByLabel(`${game.title}难度`).selectOption('challenge');
    await page.getByLabel(`${game.title}关卡`).selectOption(`${game.scene}-01`);
    const voices: string[] = [];
    page.on('request', (request) => {
      if (/\/(voice|audio)\//.test(request.url())) voices.push(request.url());
    });
    const created = page.waitForResponse(
      (r) => r.url().endsWith('/sessions') && r.request().method() === 'POST',
    );
    await page.getByRole('button', { name: `开始${game.title}` }).click();
    const session = await (await created).json();
    expect(session.tasks).toHaveLength(count);
    expect(
      new Set(
        session.tasks.map(
          (t: { exercise: { primaryKnowledgeId: string } }) => t.exercise.primaryKnowledgeId,
        ),
      ).size,
    ).toBeGreaterThanOrEqual(3);
    const stage = page.locator('.scene-stage');
    await expect(stage.locator('[data-scene-target]')).toHaveCount(
      session.tasks[0].exercise.options.length,
    );
    await expect
      .poll(() =>
        voices.some((url) => url.endsWith(`/audio/${session.tasks[0].exercise.audioRef}`)),
      )
      .toBe(true);
    expect(voices.some((url) => url.includes('/voice/prompt-'))).toBe(false);
    const originalWidth = (await stage.boundingBox())!.width;
    await page.getByRole('button', { name: '放大画面' }).click();
    expect((await stage.boundingBox())!.width).toBeGreaterThan(originalWidth);
    expect(await page.evaluate(() => document.fullscreenElement)).toBeNull();
    await page.getByRole('button', { name: '游戏设置' }).click();
    const dialog = page.getByRole('dialog', { name: '游戏设置' });
    await expect(dialog).toBeVisible();
    const distance = await stage.getAttribute('data-world-distance');
    await page.keyboard.press('ArrowRight');
    await page.waitForTimeout(300);
    expect(await stage.getAttribute('data-world-distance')).toBe(distance);
    await page.getByLabel('本关难度').selectOption('gentle');
    await page.getByLabel('本关速度').selectOption('fast');
    await page.getByLabel('下次开局题量').selectOption('20');
    await page.getByRole('button', { name: '应用设置' }).click();
    await expect(dialog).not.toBeVisible();
    const current = await (await page.request.get(`${appUrl}/api/v1/sessions/current`)).json();
    expect(current.gameSettings.level).toBe('gentle');
    expect(current.gameSettings.speed).toBe('fast');
    expect(current.gameRun).toEqual(session.gameRun);
    await page.getByRole('button', { name: '游戏设置' }).click();
    await page.keyboard.press('Escape');
    await expect(dialog).not.toBeVisible();
    await expect(page.getByRole('button', { name: '游戏设置' })).toBeFocused();
    await page.reload();
    await expect(page.getByRole('button', { name: '还原画面' })).toBeVisible();
    const restored = await (await page.request.get(`${appUrl}/api/v1/sessions/current`)).json();
    expect(restored.gameSettings).toEqual(current.gameSettings);
    for (const width of [1280, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page.getByRole('button', { name: '游戏设置' }).click();
      await expect(dialog).toBeInViewport();
      await page.getByRole('button', { name: '取消', exact: true }).click();
    }
    await page.setViewportSize({ width: 1440, height: 1100 });
    await page.screenshot({
      path: test.info().outputPath(`play-${game.scene}-enlarged.png`),
      fullPage: true,
    });
    for (let i = 0; i < count; i++) {
      await expect(page.locator('.scene-nav')).toContainText(`任务 ${i + 1} / ${count}`, {
        timeout: 15000,
      });
      const q = curriculum.exercises.find((q) => q.id === session.tasks[i].exercise.id)!;
      await playScene(page, q.answer.optionId!, { continuous: true });
      if (i < count - 1) await expect(page.getByLabel('本次练习小结')).toHaveCount(0);
    }
    await expect(page.getByLabel('本次练习小结')).toBeVisible({ timeout: 15000 });
    const backup = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
    expect(backup.attempts).toHaveLength(count);
    expect(
      backup.attempts.every((a: { first_try_correct: number }) => a.first_try_correct === 1),
    ).toBe(true);
    expect(errors).toEqual([]);
  });
}

test('PLAY-02/04: failed settings keep the draft; pointer holds release and later scenery runs faster', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '进入游戏乐园' }).click();
  await page.getByLabel('河湾划船关卡').selectOption('boat-01');
  await page.getByRole('button', { name: '开始河湾划船' }).click();
  const stage = page.locator('.scene-stage');
  await expect(stage).toBeVisible();
  const slow = Number(await stage.getAttribute('data-speed-factor'));
  await page.getByRole('button', { name: '游戏设置' }).click();
  await page.getByLabel('本关速度').selectOption('fast');
  await page.route('**/guest/operate', async (route) => {
    const body = route.request().postDataJSON();
    if (body.path?.endsWith('/game-settings')) await route.abort('failed');
    else await route.continue();
  });
  await page.getByRole('button', { name: '应用设置' }).click();
  await expect(page.getByRole('dialog')).toBeVisible();
  await expect(page.getByRole('dialog')).toContainText('暂时无法连接');
  await expect(page.getByLabel('本关速度')).toHaveValue('fast');
  await page.unroute('**/guest/operate');
  await page.getByRole('button', { name: '应用设置' }).click();
  await expect(page.getByRole('dialog')).not.toBeVisible();
  await page.getByRole('button', { name: '听拼音', exact: true }).click();
  const paddle = page.getByRole('button', { name: '双桨前进', exact: true });
  await expect(paddle).toBeEnabled({ timeout: 15000 });
  await paddle.scrollIntoViewIfNeeded();
  const box = (await paddle.boundingBox())!;
  await page.mouse.move(box.x + box.width / 2, box.y + box.height / 2);
  await page.mouse.down();
  await expect
    .poll(async () => Number(await stage.getAttribute('data-world-distance')))
    .toBeGreaterThan(15);
  await expect
    .poll(async () => Number(await stage.getAttribute('data-world-strokes')))
    .toBeGreaterThanOrEqual(3);
  await page.getByRole('button', { name: 'Ⅱ 暂停', exact: true }).press('Enter');
  await page.mouse.up();
  const stopped = await stage.getAttribute('data-world-distance');
  await page.waitForTimeout(400);
  expect(await stage.getAttribute('data-world-distance')).toBe(stopped);
  await page.getByRole('button', { name: '保存并退出游戏' }).click();
  await page.getByLabel('河湾划船关卡').selectOption('boat-06');
  await openGameSettings(page, '河湾划船');
  await page.getByLabel('河湾划船速度').selectOption('slow');
  await page.getByRole('button', { name: '开始河湾划船' }).click();
  await expect(stage).toBeVisible();
  expect(Number(await stage.getAttribute('data-speed-factor'))).toBeCloseTo(slow * 1.6);
});
