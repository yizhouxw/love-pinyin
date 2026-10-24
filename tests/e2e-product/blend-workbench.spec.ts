import { openSection } from '../support/interaction';
import { optionById } from '../support/options';
import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import curriculum from '../../content/curriculum.json' with { type: 'json' };
import narration from '../../content/narration.json' with { type: 'json' };

test('BLEND-01: real spoken preview, undo, reload, failed confirmation and single-credit correction', async ({
  page,
  appUrl,
  seedReview,
}) => {
  const submitted: Record<string, string>[] = [];
  const voices: string[] = [];
  page.on('request', (request) => {
    if (request.url().endsWith('/answer')) submitted.push(request.postDataJSON());
    if (request.url().includes('/voice/')) voices.push(request.url());
  });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  const code = (await page.locator('.pair-code').innerText()).match(/[A-Z2-9]{8}/)?.[0];
  expect(code).toBeTruthy();
  await page.getByLabel('家长配对码').fill(code!);
  await page.getByRole('button', { name: '连接家庭' }).click();
  await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeVisible();
  // Only the historical due-plan is seeded. Questions, audio, answers and storage are real.
  await seedReview('k-initial-b');
  await page.reload();
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/reviews/k-initial-b/sessions') && r.request().method() === 'POST',
  );
  await page.route('**/api/v1/voice/prompt-*', (route) => route.abort('failed'));
  await page.getByRole('region', { name: '今日推荐复习' }).getByRole('button').click();
  const session = await (await created).json();
  const question = curriculum.exercises.find((q) => q.id === session.tasks[0].exercise.id)!;
  expect(question.type).toBe('blend-choice');
  expect(question.audioRef).toBeUndefined();
  await expect(page.getByRole('button', { name: '↻ 重试声音' })).toBeVisible();
  await page.unroute('**/api/v1/voice/prompt-*');
  const correctIndex = question.options.findIndex((o) => o.id === question.answer.optionId);
  const wrongIndex = question.options.findIndex((o) => o.id !== question.answer.optionId);
  const options = page.locator('.game-option');
  const confirm = page.getByRole('button', { name: '确认拼读', exact: true });
  const undo = page.getByRole('button', { name: '撤销拼读选择', exact: true });
  await expect(options.first()).toBeEnabled({ timeout: 20000 });
  await optionById(page, question.options[wrongIndex]!.id).press('Enter');
  await expect(confirm).toBeEnabled();
  await expect(confirm).toBeFocused();
  await expect(confirm).toBeInViewport();
  await expect(page.getByLabel('当前拼读预览')).toContainText(question.options[wrongIndex]!.label);
  await expect.poll(() => voices.some((url) => url.endsWith('/voice/ui-blend_ready'))).toBe(true);
  expect(submitted).toEqual([]);
  await undo.press('Enter');
  await expect(optionById(page, question.options[wrongIndex]!.id)).toBeFocused();
  await expect(optionById(page, question.options[wrongIndex]!.id)).toBeInViewport();
  await expect(page.getByLabel('当前拼读预览')).toHaveCount(0);
  await optionById(page, question.options[correctIndex]!.id).press('Enter');
  await page.reload();
  await expect(page.getByLabel('当前拼读预览')).toHaveCount(0);
  await expect(page.locator('.play-nav')).toContainText('两题复习');
  await expect(page.locator('.session-size-note')).toHaveCount(0);
  await expect(page.locator('.draft-banner')).toHaveCount(0);
  expect(submitted).toEqual([]);
  await openSection(page, '听题目说明', true);
  await page.getByRole('button', { name: '听题目', exact: true }).click();
  await expect(options.first()).toBeEnabled({ timeout: 20000 });
  await optionById(page, question.options[wrongIndex]!.id).press('Enter');
  await page.screenshot({ path: test.info().outputPath('blend-preview.png'), fullPage: true });
  const answerPattern = `**/instances/${session.tasks[0].instanceId}/answer`;
  await page.route(answerPattern, (route) => route.abort('failed'));
  await confirm.press('Enter');
  await expect(page.getByRole('alert')).toContainText('本次操作尚未确认');
  await expect(page.getByLabel('当前拼读预览')).toContainText(question.options[wrongIndex]!.label);
  expect(submitted).toHaveLength(1);
  await page.unroute(answerPattern);
  await confirm.press('Enter');
  await expect(page.locator('.feedback')).toContainText('没关系');
  await expect(page.locator('.answer-explanation')).toContainText(
    new RegExp(narration.exercises[question.id as keyof typeof narration.exercises].hint),
  );
  await openSection(page, '听讲解');
  await expect(page.getByRole('button', { name: '停止重听讲解', exact: true })).toBeVisible();
  await expect
    .poll(() => voices.some((url) => url.endsWith(`/voice/hint-${question.id}`)))
    .toBe(true);
  expect(submitted).toHaveLength(2);
  expect(submitted[1]).toEqual(submitted[0]);
  // Feedback can render before the progress refresh releases the busy state.
  // Keyboard presses do not wait for enabled controls as mouse clicks do.
  await expect(optionById(page, question.options[correctIndex]!.id)).toBeEnabled();
  await optionById(page, question.options[correctIndex]!.id).press('Enter');
  await confirm.press('Enter');
  await expect(page.locator('.feedback')).toContainText('找到正确答案啦');
  expect(submitted).toHaveLength(2);
  await page.getByRole('button', { name: '继续 →', exact: true }).click();
  await expect(page.locator('.play-nav strong')).toHaveText('第 2 / 2 关');
  await expect(page.getByLabel('当前拼读预览')).toHaveCount(0);
  await page.getByRole('button', { name: '先跳过这题' }).click();
  await page.getByRole('button', { name: '回到小岛', exact: true }).click();
  await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeVisible();
  const exported = await page.request.get(`${appUrl}/api/v1/profiles/export`);
  expect(exported.ok()).toBe(true);
  const backup = await exported.json();
  expect(backup.attempts).toHaveLength(1);
  expect(backup.attempts[0].first_try_correct).toBe(0);
  expect(backup.attempts[0].hint_used).toBe(0);
  expect(backup.sessions[0].status).toBe('finished');
});
