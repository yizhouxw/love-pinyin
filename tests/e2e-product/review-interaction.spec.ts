import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import curriculum from '../../content/curriculum.json' with { type: 'json' };
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
    const round = await (await created).json();
    const exercise = curriculum.exercises.find((item) => item.id === round.tasks[0].exercise.id)!;
    const option = exercise.options.find((item) => item.id === exercise.answer.optionId)!;
    const stage = page.getByRole('group', { name: '场景动作' });
    await expect(stage).toBeVisible();
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await expect(stage).toHaveCount(0);
    await expect(page.locator('.scene-nav')).toContainText('任务 1 /');
    const choices = page.getByRole('group', { name: '直接选择拼音' });
    await choices.getByRole('button', { name: option.label, exact: true }).click();
    await expect(page.locator('.scene-nav')).toContainText('任务 2 /');
  });
}
