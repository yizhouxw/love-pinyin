import { openGameSettings } from '../support/interaction';
import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import { playScene } from '../support/scene-actions';
import curriculum from '../../content/curriculum.json' with { type: 'json' };
import catalog from '../../content/games.json' with { type: 'json' };

test.use({ selectedPinyinSource: true });
for (const game of catalog.games) {
  test(`SCENE ${game.scene}: actual action collision, voiced first-lesson play, pause, settings and first answer`, async ({
    page,
    appUrl,
  }) => {
    const errors: string[] = [];
    const voices: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('request', (request) => {
      if (request.url().includes('/voice/')) voices.push(request.url());
    });
    await page.goto(appUrl);
    await page.getByRole('button', { name: '在本机生成家长配对码' }).click();
    await page.getByRole('button', { name: '连接家庭' }).click();
    await page.getByRole('button', { name: '进入游戏乐园' }).click();
    await openGameSettings(page, game.title);
    await page.getByLabel(`${game.title}难度`).selectOption('gentle');
    await page.getByLabel(`${game.title}速度`).selectOption('fast');
    const created = page.waitForResponse(
      (r) => r.url().endsWith('/sessions') && r.request().method() === 'POST',
    );
    await page.getByRole('button', { name: `开始${game.title}` }).click();
    const session = await (await created).json();
    expect(session.gameSettings.level).toBe('gentle');
    expect(session.gameSettings.speed).toBe('fast');
    expect(
      session.tasks.every(
        (t: { exercise: { lessonId: string } }) => t.exercise.lessonId === 'lesson-01',
      ),
    ).toBe(true);
    await expect(page.getByLabel('本关任务').getByRole('heading')).toHaveText(game.controls);
    await page.getByRole('button', { name: '玩法与故事', exact: true }).click();
    await expect(page.getByRole('button', { name: '听题目说明', exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: '听玩法', exact: true }).click();
    await expect
      .poll(() => voices.some((url) => url.endsWith(`/voice/${game.voiceId}`)))
      .toBe(true);
    await page.getByRole('dialog').getByRole('button', { name: '关闭', exact: true }).click();
    await page.getByRole('button', { name: 'Ⅱ 暂停', exact: true }).click();
    const stage = page.getByRole('group', { name: '游戏操作区：方向键控制，空格行动' });
    const position = await stage.getAttribute('data-world-distance');
    await page.waitForTimeout(250);
    expect(await stage.getAttribute('data-world-distance')).toBe(position);
    await page.getByRole('button', { name: '▶ 继续游戏', exact: true }).click();
    await expect(page.locator('.game-option')).toHaveCount(0);
    const q = curriculum.exercises.find((q) => q.id === session.tasks[0].exercise.id)!;
    const originalStage = await stage.elementHandle();
    await playScene(page, q.answer.optionId!);
    await expect(page.locator('.scene-nav')).toContainText('任务 2 / 6');
    expect(
      await originalStage!.evaluate(
        (element) => element === document.querySelector('.scene-stage'),
      ),
    ).toBe(true);
    await expect(page.getByRole('button', { name: '继续航程 →' })).toHaveCount(0);
    const backup = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
    expect(backup.attempts).toHaveLength(1);
    expect(backup.attempts[0].first_try_correct).toBe(1);
    for (const [width, height] of [
      [1280, 720],
      [390, 844],
      [320, 568],
      [844, 390],
    ] as const) {
      await page.setViewportSize({ width, height });
      await expect(page.getByRole('group', { name: '场景动作' })).toBeInViewport({ ratio: 0.98 });
      expect(
        await page
          .locator('.scene-response')
          .evaluate((element) => getComputedStyle(element).overflowY),
      ).toBe('visible');
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
        true,
      );
      await page.screenshot({
        path: test.info().outputPath(`scene-${game.scene}-${width}.png`),
        fullPage: true,
      });
    }
    await page.reload();
    const restored = await (await page.request.get(`${appUrl}/api/v1/sessions/current`)).json();
    expect(restored.gameSettings).toEqual(session.gameSettings);
    expect(restored.tasks).toEqual(session.tasks);
    await expect(page.getByLabel('本关任务')).toBeVisible();
    expect(restored.gameRun).toEqual(session.gameRun);
    await expect(page.locator('.scene-nav')).toContainText('任务 2 / 6');
    const second = curriculum.exercises.find((q) => q.id === session.tasks[1].exercise.id)!;
    await playScene(page, second.answer.optionId!);
    await expect(page.locator('.scene-nav')).toContainText('任务 3 / 6');
    const more = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
    expect(more.attempts).toHaveLength(2);

    await page.getByRole('button', { name: '保存并退出游戏' }).click();
    await expect(page.getByLabel(`${game.title}速度`)).toHaveValue('fast');
    expect(errors).toEqual([]);
  });
}

test('SCENE-05: an unconfirmed collision stays frozen and reload replays only the original choice', async ({
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
  await page.getByRole('button', { name: '开始节奏鼓岛' }).click();
  const session = await (await created).json();
  const question = curriculum.exercises.find((q) => q.id === session.tasks[0].exercise.id)!;
  const original = question.answer.optionId!;
  await page.route('**/instances/*/answer', (route) => route.abort('failed'));
  await playScene(page, original);
  await expect(page.getByRole('button', { name: '重试保存这次选择' })).toBeVisible();
  await expect(
    page.getByRole('group', { name: '场景动作' }).getByRole('button').nth(1),
  ).toBeDisabled();
  let data = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
  expect(data.attempts).toHaveLength(0);
  await page.unroute('**/instances/*/answer');
  await page.reload();
  await page.getByRole('button', { name: '听拼音', exact: true }).click();
  await expect(page.locator('.scene-nav')).toContainText('任务 2 /');
  data = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
  expect(data.attempts).toHaveLength(1);
  expect(JSON.parse(data.attempts[0].answer_json).optionId).toBe(original);
});
