import { openSection } from '../support/interaction';
import { optionById } from '../support/options';
import { expect } from '@playwright/test';
import curriculum from '../../content/curriculum.json' with { type: 'json' };
import { test } from '../support/real-server';

test.use({ selectedPinyinSource: true });

test('BANK-04: real course rotation reaches b, q and sh syllable listening with local voices', async ({
  page,
  appUrl,
}) => {
  test.setTimeout(180_000);
  const submitted: string[] = [];
  const external: string[] = [];
  page.on('request', (r) => {
    if (r.url().endsWith('/answer')) submitted.push(r.url());
    if (r.url().startsWith('http') && new URL(r.url()).origin !== appUrl) external.push(r.url());
  });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  const code = (await page.locator('.pair-code').innerText()).match(/[A-Z2-9]{8}/)![0];
  await page.getByLabel('家长配对码').fill(code);
  await page.getByRole('button', { name: '连接家庭' }).click();
  const heard: string[] = [];
  let breaks = 0;
  let checkedPendingRefresh = false;
  for (const initial of ['b', 'q', 'sh']) {
    const knowledge = curriculum.knowledgeItems.find((k) => k.id === `k-initial-${initial}`)!;
    const wanted = curriculum.exercises.filter(
      (q) =>
        q.primaryKnowledgeId === knowledge.id &&
        Number(q.id.split('-').at(-1)) >= 70 &&
        Number(q.id.split('-').at(-1)) < 80,
    );
    expect(wanted).toHaveLength(2);
    await page.getByRole('button', { name: '家长管理' }).click();
    await page.getByRole('button', { name: '我是家长，继续' }).click();
    await page.getByRole('combobox').selectOption(knowledge.lessonId);
    const saved = page.waitForResponse(
      (r) => r.url().endsWith('/household/current-lesson') && r.request().method() === 'PUT',
    );
    await page.getByRole('button', { name: '保存', exact: true }).click();
    expect((await saved).ok()).toBe(true);
    await page.getByRole('button', { name: '返回学习', exact: true }).click();
    const lessonQuestions = curriculum.exercises.filter(
      (q) => q.lessonId === knowledge.lessonId && q.type !== 'read-aloud',
    );
    for (let round = 0; round < Math.ceil(lessonQuestions.length / 6); round += 1) {
      const created = page.waitForResponse(
        (r) => r.url().endsWith('/sessions') && r.request().method() === 'POST',
      );
      await page.getByRole('button', { name: '开始今天的练习' }).click();
      const session = await (await created).json();
      for (const [index, task] of session.tasks.entries()) {
        const q = wanted.find((q) => q.id === task.exercise.id);
        await expect(page.locator('.play-nav strong')).toHaveText(`第 ${index + 1} / 6 关`);
        if (!q || heard.includes(q.id)) {
          await page.getByRole('button', { name: '↷ 先跳过这题' }).click();
          continue;
        }
        await expect(page.getByLabel('观察目标')).toHaveCount(0);
        await expect(page.locator('.game-option').first()).toBeDisabled();
        const audio = page.waitForResponse(
          (r) => r.url().endsWith(`/audio/${q.audioRef}`) && r.ok(),
        );
        await openSection(page, '听题目说明', true);
        await expect(page.getByRole('button', { name: '停止听题目', exact: true })).toBeVisible();
        await expect(page.getByRole('button', { name: '听题目', exact: true })).toBeVisible({
          timeout: 20000,
        });
        await audio;
        await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 20000 });
        const choice = q.options.findIndex((o) => o.id === q.answer.optionId);
        await optionById(page, q.options[choice]!.id).press('Enter');
        await expect(page.locator('.feedback')).toContainText('答对啦');
        await openSection(page, '听讲解');
        await page.getByRole('button', { name: '重听讲解', exact: true }).click();
        await expect(page.getByRole('button', { name: '停止重听讲解', exact: true })).toBeVisible();
        await expect(page.getByRole('button', { name: '重听讲解', exact: true })).toBeVisible({
          timeout: 20000,
        });
        if (initial === 'sh' && q === wanted[1])
          await page.screenshot({
            path: test.info().outputPath('initial-in-syllable.png'),
            fullPage: true,
          });
        heard.push(q.id);
        await page.getByRole('button', { name: '继续 →', exact: true }).click();
      }
      await expect(page.getByLabel('本次练习小结')).toBeVisible();
      const finished = page.waitForResponse(
        (r) =>
          r.url().endsWith(`/sessions/${session.id}/finish`) && r.request().method() === 'POST',
      );
      const inspectPendingRefresh = !checkedPendingRefresh && heard.length === 1;
      let releaseRefresh = () => {};
      let pendingProgress: Promise<unknown> | undefined;
      if (inspectPendingRefresh) {
        // Delay a real response, never replace it: reproduce entering the
        // parent screen while the previous round's progress is still loading.
        const hold = new Promise<void>((resolve) => {
          releaseRefresh = resolve;
        });
        await page.route('**/api/v1/profiles/progress', async (route) => {
          await hold;
          await route.continue();
        });
        pendingProgress = page.waitForRequest((r) => r.url().endsWith('/profiles/progress'));
      }
      await page.getByRole('button', { name: '回到小岛' }).click();
      const result = await (await finished).json();
      if (inspectPendingRefresh) {
        try {
          await pendingProgress;
          expect(result.breakRequired).toBe(false);
          await page.getByRole('button', { name: '家长管理' }).click();
          await page.getByRole('button', { name: '我是家长，继续' }).click();
          await expect(page.getByRole('combobox')).toBeDisabled();
          await expect(page.getByRole('button', { name: '保存', exact: true })).toBeDisabled();
        } finally {
          releaseRefresh();
        }
        await expect(page.getByRole('combobox')).toBeEnabled();
        await page.unroute('**/api/v1/profiles/progress');
        await page.getByRole('button', { name: '返回学习', exact: true }).click();
        checkedPendingRefresh = true;
      }
      if (result.breakRequired) {
        breaks += 1;
        await page.getByRole('button', { name: '休息好了，继续学习' }).click();
      }
      if (wanted.every((q) => heard.includes(q.id))) break;
    }
    expect(wanted.every((q) => heard.includes(q.id))).toBe(true);
  }
  expect(breaks).toBeGreaterThan(0);
  expect(checkedPendingRefresh).toBe(true);
  expect(heard).toHaveLength(6);
  expect(submitted).toHaveLength(6);
  await page.reload();
  await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeVisible();
  const backup = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
  expect(backup.attempts.map((a: { exercise_id: string }) => a.exercise_id).sort()).toEqual(
    heard.sort(),
  );
  expect(
    backup.attempts.every((a: { first_try_correct: number }) => a.first_try_correct === 1),
  ).toBe(true);
  expect(external).toEqual([]);
});
