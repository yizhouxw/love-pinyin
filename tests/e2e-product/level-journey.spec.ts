import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import { playScene } from '../support/scene-actions';
import curriculum from '../../content/curriculum.json' with { type: 'json' };

test.use({ selectedPinyinSource: true });
test('LEVEL-01/KEY-01: play one complete twelve-task forest journey using normal keyboard focus', async ({
  page,
  appUrl,
}) => {
  test.setTimeout(420000);
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭' }).click();
  await page.getByRole('button', { name: '进入游戏乐园' }).click();
  await page.getByLabel('森林跑酷难度').selectOption('gentle');
  await page.getByLabel('森林跑酷速度').selectOption('fast');
  await page.getByLabel('森林跑酷关卡').selectOption('runner-01');
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/sessions') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: '开始森林跑酷' }).click();
  const session = await (await created).json();
  expect(session.tasks).toHaveLength(12);
  expect(
    new Set(session.tasks.map((t: { exercise: { audioRef: string } }) => t.exercise.audioRef)).size,
  ).toBeGreaterThanOrEqual(3);
  for (let i = 0; i < 12; i++) {
    await expect(page.locator('.scene-nav')).toContainText(`任务 ${i + 1} / 12`, {
      timeout: 15000,
    });
    await expect(page.getByLabel('完整关卡路线')).toContainText(
      session.gameRun.level.chapters[Math.floor(i / 4)].title,
    );
    const q = curriculum.exercises.find((q) => q.id === session.tasks[i].exercise.id)!;
    await playScene(page, q.answer.optionId!, { continuous: true });
    if (i < 11) await expect(page.getByLabel('本次练习小结')).toHaveCount(0);
  }
  await expect(page.getByLabel('本次练习小结')).toBeVisible({ timeout: 15000 });
  const backup = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
  expect(backup.attempts).toHaveLength(12);
  expect(
    backup.attempts.every((a: { first_try_correct: number }) => a.first_try_correct === 1),
  ).toBe(true);
  expect(errors).toEqual([]);
});
