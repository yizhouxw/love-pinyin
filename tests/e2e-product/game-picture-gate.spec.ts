import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import { playScene } from '../support/scene-actions';
import curriculum from '../../content/curriculum.json' with { type: 'json' };

test.use({ selectedPinyinSource: true });

test('ANDROID-03: scene target answers do not wait for unmounted classroom pictures', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在本机生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭' }).click();
  // Keep the real server session and answers, but attach a classroom-only picture
  // to the delivered task. A scene never mounts that illustration.
  await page.route('**/api/v1/sessions', async (route) => {
    const response = await route.fetch();
    const session = await response.json();
    for (const task of session.tasks ?? []) task.exercise.pictureId = 'unmounted-classroom-picture';
    await route.fulfill({ response, json: session });
  });
  await page.getByRole('button', { name: '进入游戏乐园' }).click();
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/sessions') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: '开始星际投递' }).click();
  const session = await (await created).json();
  const task = session.tasks[0];
  const question = curriculum.exercises.find((q) => q.id === task.exercise.id)!;
  await playScene(page, question.answer.optionId!);
  await expect(page.locator('.scene-nav')).toContainText('任务 2 /', { timeout: 20000 });
});
