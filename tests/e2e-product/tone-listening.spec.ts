import { expect } from '@playwright/test';
import curriculum from '../../content/curriculum.json' with { type: 'json' };
import { test } from '../support/real-server';

test.use({ selectedPinyinSource: true });

test('TONE-01: course rotation reaches all twelve recorded tones with spoken feedback and saved answers', async ({
  page,
  appUrl,
}) => {
  test.setTimeout(180_000);
  const submitted: string[] = [];
  page.on('request', (r) => {
    if (r.url().endsWith('/answer')) submitted.push(r.url());
  });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  const code = (await page.locator('.pair-code').innerText()).match(/[A-Z2-9]{8}/)![0];
  await page.getByLabel('家长配对码').fill(code);
  await page.getByRole('button', { name: '连接家庭' }).click();
  const heard: string[] = [];
  const seen: string[] = [];
  let wrongId = '';
  for (let round = 0; round < 5; round += 1) {
    if (round > 0 && round % 2 === 0)
      await page.getByRole('button', { name: '休息好了，继续学习' }).click();
    const started = page.waitForResponse(
      (r) => r.url().endsWith('/sessions') && r.request().method() === 'POST',
    );
    await page.getByRole('button', { name: '开始今天的练习' }).click();
    const session = await (await started).json();
    expect(session.tasks).toHaveLength(6);
    for (const [index, task] of session.tasks.entries()) {
      const question = curriculum.exercises.find((q) => q.id === task.exercise.id)!;
      await expect(page.locator('.play-nav strong')).toHaveText(`第 ${index + 1} / 6 关`);
      if (round < 3) {
        await page.getByRole('button', { name: '↷ 先跳过这题' }).click();
        continue;
      }
      expect(question.type).toBe('tone-choice');
      expect(question.audioRef).toBeTruthy();
      seen.push(question.id);
      await expect(page.getByText('声调听辨站', { exact: true })).toBeVisible();
      await expect(page.getByLabel('观察目标')).toHaveCount(0);
      await expect(page.locator('.feedback')).toHaveCount(0);
      await expect(page.locator('.game-option').first()).toBeDisabled();
      await expect(page.getByRole('button', { name: '停止听题目', exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: '听题目', exact: true })).toBeVisible({
        timeout: 20000,
      });
      await expect(page.locator('.game-option').first()).toBeDisabled();
      const audio = page.waitForResponse(
        (r) => r.url().endsWith(`/audio/${question.audioRef}`) && r.ok(),
      );
      await page.getByRole('button', { name: '听拼音', exact: true }).press('Enter');
      await audio;
      await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 20000 });
      heard.push(question.audioRef!);
      const choice = question.options.findIndex((o) => o.id === question.answer.optionId);
      if (!wrongId) {
        wrongId = question.id;
        await page
          .locator('.game-option')
          .nth((choice + 1) % 4)
          .click();
        await expect(page.getByRole('button', { name: '停止听讲解', exact: true })).toBeVisible();
        await expect(page.getByRole('button', { name: '听讲解', exact: true })).toBeVisible({
          timeout: 20000,
        });
        expect(submitted).toHaveLength(1);
        await page.locator('.game-option').nth(choice).press('Enter');
        expect(submitted).toHaveLength(1);
        await page.screenshot({
          path: test.info().outputPath('four-tone-correction.png'),
          fullPage: true,
        });
      } else {
        await page.locator('.game-option').nth(choice).press('Enter');
        await expect(page.locator('.feedback')).toContainText('答对啦');
      }
      await page.getByRole('button', { name: '继续 →', exact: true }).click();
    }
    await expect(page.getByLabel('本次练习小结')).toBeVisible();
    await page.getByRole('button', { name: '回到小岛' }).click();
  }
  const expected = curriculum.exercises.filter((q) => q.type === 'tone-choice' && q.audioRef);
  expect(seen.sort()).toEqual(expected.map((q) => q.id).sort());
  expect(new Set(heard).size).toBe(12);
  expect(submitted).toHaveLength(12);
  const backup = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
  expect(backup.attempts).toHaveLength(12);
  expect(backup.attempts.map((a: { exercise_id: string }) => a.exercise_id).sort()).toEqual(seen);
  for (const attempt of backup.attempts)
    expect(attempt.first_try_correct).toBe(attempt.exercise_id === wrongId ? 0 : 1);

  // Reach the same question in a later instance without reloading: earlier
  // playback must not satisfy this instance's listening requirement.
  const lessonSize = curriculum.exercises.filter(
    (q) => q.lessonId === 'lesson-01' && q.type !== 'read-aloud',
  ).length;
  let repeatedChecked = false;
  for (let round = 5; round < 5 + Math.ceil(lessonSize / 6) && !repeatedChecked; round += 1) {
    if (round % 2 === 0) await page.getByRole('button', { name: '休息好了，继续学习' }).click();
    const started = page.waitForResponse(
      (r) => r.url().endsWith('/sessions') && r.request().method() === 'POST',
    );
    await page.getByRole('button', { name: '开始今天的练习' }).click();
    const repeated = await (await started).json();
    for (const [index, task] of repeated.tasks.entries()) {
      await expect(page.locator('.play-nav strong')).toHaveText(`第 ${index + 1} / 6 关`);
      if (task.exercise.id !== wrongId) {
        await page.getByRole('button', { name: '↷ 先跳过这题' }).click();
        continue;
      }
      await expect(page.getByRole('button', { name: '停止听题目', exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: '听题目', exact: true })).toBeVisible({
        timeout: 20000,
      });
      await expect(page.locator('.game-option').first()).toBeDisabled();
      await page.getByRole('button', { name: '听拼音', exact: true }).press('Enter');
      await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 20000 });
      await page.getByRole('button', { name: '退出练习' }).click();
      expect(submitted).toHaveLength(12);
      repeatedChecked = true;
      break;
    }
    if (!repeatedChecked) await page.getByRole('button', { name: '回到小岛' }).click();
  }
  expect(repeatedChecked).toBe(true);
  await page.reload();
  await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeVisible();
  const restored = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
  expect(restored.attempts).toEqual(backup.attempts);
});
