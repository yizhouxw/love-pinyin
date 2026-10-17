import { optionById } from '../support/options';
import { readFile } from 'node:fs/promises';
import { expect } from '@playwright/test';
import curriculum from '../../content/curriculum.json' with { type: 'json' };
import { test } from '../support/real-server';

// This suite requires actual prepared family audio. Missing files fail rather than skip.
// It never replaces Audio, speech APIs, API responses or the learning database.
test('VOICE-05: actual narration and course audio decode, replay and separate from answering', async ({
  page,
  appUrl,
}) => {
  const errors: string[] = [];
  const answerRequests: string[] = [];
  const voiceRequests: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  page.on('request', (request) => {
    if (request.url().includes('/answer')) answerRequests.push(request.url());
    if (request.url().includes('/voice/')) voiceRequests.push(request.url());
  });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  const code = (await page.locator('.pair-code').innerText()).match(/[A-Z2-9]{8}/)?.[0];
  expect(code).toBeTruthy();
  await page.getByLabel('家长配对码').fill(code!);
  await page.getByRole('button', { name: '连接家庭' }).click();
  await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeVisible();

  const decoded = await page.evaluate(async () => {
    const status = await fetch('/api/v1/learning-audio').then((response) => response.json());
    const narration = status.narration as Record<string, boolean>;
    const lessons = status.lessons as Record<string, { audioId: string; available: boolean }>;
    const unavailable = Object.entries(narration)
      .filter(([, ready]) => !ready)
      .map(([id]) => id);
    const unavailableLessons = Object.entries(lessons)
      .filter(([, asset]) => !asset.available)
      .map(([id]) => id);
    const ids = [
      ...Object.keys(narration),
      ...new Set(Object.values(lessons).map((asset) => asset.audioId)),
    ];
    const context = new AudioContext();
    const assets: { id: string; seconds: number; peak: number }[] = [];
    try {
      for (const id of ids) {
        const response = await fetch(`/api/v1/voice/${encodeURIComponent(id)}`);
        if (!response.ok) throw new Error(`${id}: HTTP ${response.status}`);
        const audio = await context.decodeAudioData(await response.arrayBuffer());
        const samples = audio.getChannelData(0);
        let peak = 0;
        for (let index = 0; index < samples.length; index += 16) {
          peak = Math.max(peak, Math.abs(samples[index] ?? 0));
        }
        assets.push({ id, seconds: audio.duration, peak });
      }
    } finally {
      await context.close();
    }
    return { unavailable, unavailableLessons, lessonCount: Object.keys(lessons).length, assets };
  });
  expect(decoded.unavailable).toEqual([]);
  expect(decoded.unavailableLessons).toEqual([]);
  expect(decoded.lessonCount).toBe(14);
  expect(decoded.assets.filter((asset) => asset.id.startsWith('prompt-'))).toHaveLength(
    curriculum.exercises.filter((question) => question.type !== 'read-aloud').length,
  );
  for (const asset of decoded.assets) {
    expect(asset.seconds, asset.id).toBeGreaterThan(0.1);
    expect(asset.peak, asset.id).toBeGreaterThan(0.001);
  }

  await page.getByRole('button', { name: '听本课录音' }).click();
  const courseAudio = page.locator('.family-course-audio audio');
  await expect(courseAudio).toHaveAttribute('controls', '');
  await page.getByRole('button', { name: '播放课程录音', exact: true }).click();
  await expect
    .poll(() => courseAudio.evaluate((element) => (element as HTMLAudioElement).currentTime))
    .toBeGreaterThan(0);
  await page.getByRole('button', { name: '停止播放课程录音', exact: true }).click();
  const position = await courseAudio.evaluate(
    (element) => (element as HTMLAudioElement).currentTime,
  );
  await expect
    .poll(() => courseAudio.evaluate((element) => (element as HTMLAudioElement).paused))
    .toBe(true);
  await page.getByRole('button', { name: '播放课程录音', exact: true }).click();
  await expect
    .poll(() => courseAudio.evaluate((element) => (element as HTMLAudioElement).currentTime))
    .toBeGreaterThan(position);
  await page.getByRole('button', { name: '返回学习路线' }).click();

  voiceRequests.length = 0;
  await page.getByRole('button', { name: '开始今天的练习' }).click();
  await expect(page.getByRole('button', { name: '停止听题目', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '停止听题目', exact: true }).click();
  await page.getByRole('button', { name: '听题目', exact: true }).click();
  await expect(page.getByRole('button', { name: '停止听题目', exact: true })).toBeVisible();
  await expect.poll(() => voiceRequests.some((url) => url.includes('/voice/prompt-'))).toBe(true);
  expect(answerRequests).toEqual([]);
  await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 15_000 });

  // Advance through the actual first lesson to a Chinese-labelled choice.
  for (let index = 0; index < 6; index += 1) {
    if (await page.getByRole('button', { name: '听选项 A', exact: true }).count()) break;
    const previousStep = await page.locator('.play-nav strong').innerText();
    await page.getByRole('button', { name: '先跳过这题' }).click();
    await expect(page.locator('.play-nav strong')).not.toHaveText(previousStep);
  }
  await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 20000 });
  await page.getByRole('button', { name: '听选项 A', exact: true }).click();
  await expect(page.getByRole('button', { name: '停止听选项 A', exact: true })).toBeVisible();
  expect(answerRequests).toEqual([]);
  await expect.poll(() => voiceRequests.some((url) => url.includes('/voice/option-'))).toBe(true);

  await expect(page.getByRole('button', { name: '听选项 A', exact: true })).toBeVisible();
  await page.route('**/api/v1/voice/option-*', (route) => route.abort('failed'));
  await page.getByRole('button', { name: '听选项 A', exact: true }).click();
  await expect(page.getByRole('button', { name: '↻ 重试声音' })).toBeVisible();
  await expect(page.locator('.game-option').first()).toBeEnabled();
  expect(answerRequests).toEqual([]);
  await page.unroute('**/api/v1/voice/option-*');
  // Inject a failure for the question recording, not an unrelated in-flight option.
  await page.route('**/api/v1/voice/prompt-*', (route) => route.abort('failed'));
  await page.getByRole('button', { name: '听题目', exact: true }).click();
  await expect(page.getByRole('button', { name: '↻ 重试声音' })).toBeVisible();
  await expect(page.locator('.game-option').first()).toBeDisabled();
  expect(answerRequests).toEqual([]);
  await page.unroute('**/api/v1/voice/prompt-*');
  await page.getByRole('button', { name: '↻ 重试声音' }).click();
  await expect(page.getByRole('button', { name: '停止听题目', exact: true })).toBeVisible();
  await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 15_000 });
  // The instruction says “above”; the visible pinyin must match that spatial cue.
  const cue = await page.getByLabel('观察目标').boundingBox();
  const question = await page.locator('.question-card h1').boundingBox();
  expect(cue).not.toBeNull();
  expect(question).not.toBeNull();
  expect(cue!.y + cue!.height).toBeLessThanOrEqual(question!.y);
  await page.screenshot({ path: test.info().outputPath('spoken-question.png'), fullPage: true });
  await page.getByRole('button', { name: '退出练习' }).click();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await expect(page.getByText(/· 0 次练习记录/)).toBeVisible();
  expect(errors).toEqual([]);
});

test('VOICE-05: unknown resource status cannot unlock silent answers; exit stops hint', async ({
  page,
  appUrl,
}) => {
  const answerRequests: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/answer')) answerRequests.push(request.url());
  });
  await page.route('**/api/v1/learning-audio', (route) => route.abort('failed'));
  await page.route('**/api/v1/voice/prompt-*', (route) => route.abort('failed'));
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  const code = (await page.locator('.pair-code').innerText()).match(/[A-Z2-9]{8}/)?.[0];
  expect(code).toBeTruthy();
  await page.getByLabel('家长配对码').fill(code!);
  await page.getByRole('button', { name: '连接家庭' }).click();
  await page.getByRole('button', { name: '开始今天的练习' }).click();
  await expect(page.getByRole('button', { name: '↻ 重试声音' })).toBeVisible();
  for (const option of await page.locator('.game-option').all())
    await expect(option).toBeDisabled();
  expect(answerRequests).toEqual([]);
  await page.unroute('**/api/v1/voice/prompt-*');
  await page.getByRole('button', { name: '↻ 重试声音' }).click();
  await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 15_000 });
  await page.getByRole('button', { name: '给我一点提示' }).click();
  await expect(page.getByRole('button', { name: '停止听提示' })).toBeVisible();
  await page.getByRole('button', { name: '退出练习' }).click();
  await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeVisible();
  await page.getByRole('button', { name: '开始今天的练习' }).click();
  // A retained hint used to auto-play on the next session instead of its question.
  await expect(page.getByRole('button', { name: '停止听题目' })).toBeVisible();
  await expect(page.locator('.hint-box')).toHaveCount(0);
  await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 15_000 });
  expect(answerRequests).toEqual([]);
});

test('FEEDBACK-01: spoken correction retries without another answer or hint credit', async ({
  page,
  appUrl,
}) => {
  const answerRequests: string[] = [];
  const hintRequests: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/answer')) answerRequests.push(request.url());
    if (request.url().endsWith('/hint')) hintRequests.push(request.url());
  });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  const code = (await page.locator('.pair-code').innerText()).match(/[A-Z2-9]{8}/)?.[0];
  expect(code).toBeTruthy();
  await page.getByLabel('家长配对码').fill(code!);
  await page.getByRole('button', { name: '连接家庭' }).click();
  await page.getByRole('button', { name: '开始今天的练习' }).click();
  await expect(page.getByRole('heading', { name: '哪张卡片是第一声？' })).toBeVisible();
  const choices = page.locator('.game-option');
  await expect(choices.first()).toBeEnabled({ timeout: 15_000 });
  await page.route('**/api/v1/voice/hint-*', (route) => route.abort('failed'));
  const correctionQuestion = curriculum.exercises.find((q) => q.id === 'q-01-04')!;
  const wrongId = correctionQuestion.options.find(
    (o) => o.id !== correctionQuestion.answer.optionId,
  )!.id;
  await optionById(page, wrongId).click();
  await expect(page.locator('.feedback')).toContainText('再选一次');
  await expect(page.locator('.answer-explanation')).toContainText('第一声的声调记号是平平的一横');
  await expect(page.getByRole('button', { name: '↻ 重试声音' })).toBeVisible();
  await page.unroute('**/api/v1/voice/hint-*');
  await page.getByRole('button', { name: '↻ 重试声音' }).click();
  await expect(page.getByRole('button', { name: '停止听讲解', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '停止听讲解', exact: true }).click();
  await page.getByRole('button', { name: '听讲解', exact: true }).press('Enter');
  await expect(page.getByRole('button', { name: '停止听讲解', exact: true })).toBeVisible();
  await expect(choices.first()).toBeEnabled();
  await optionById(page, correctionQuestion.answer.optionId).press('Enter');
  await expect(page.locator('.feedback')).toContainText('找到正确答案啦');
  expect(answerRequests).toHaveLength(1);
  expect(hintRequests).toEqual([]);
  await page.getByRole('button', { name: '退出练习' }).click();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await expect(page.getByText(/· 1 次练习记录/)).toBeVisible();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: '导出家庭数据' }).click();
  const download = await downloadPromise;
  const file = await download.path();
  expect(file).toBeTruthy();
  const saved = JSON.parse(await readFile(file!, 'utf8'));
  const backup = page.getByLabel('导出的 JSON 数据');
  await expect(backup).toBeVisible();
  expect(JSON.parse(await backup.inputValue())).toEqual(saved);
  expect(saved.attempts).toHaveLength(1);
  expect(saved.attempts[0].first_try_correct).toBe(0);
  expect(saved.attempts[0].hint_used).toBe(0);
});

test('BANK-01: the former two-question nasal lesson completes six spoken tasks', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  const code = (await page.locator('.pair-code').innerText()).match(/[A-Z2-9]{8}/)?.[0];
  expect(code).toBeTruthy();
  await page.getByLabel('家长配对码').fill(code!);
  await page.getByRole('button', { name: '连接家庭' }).click();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await page.getByRole('combobox').selectOption('lesson-13');
  const saved = page.waitForResponse(
    (response) =>
      response.url().endsWith('/household/current-lesson') && response.request().method() === 'PUT',
  );
  await page.getByRole('button', { name: '保存', exact: true }).click();
  expect((await saved).ok()).toBe(true);
  await page.getByRole('button', { name: '返回学习', exact: true }).click();
  await expect(
    page.getByRole('heading', { name: '第 13 课 · an en in un ün', exact: true }),
  ).toBeVisible();
  const sessionResponse = page.waitForResponse(
    (response) => response.url().endsWith('/sessions') && response.request().method() === 'POST',
  );
  await page.getByRole('button', { name: '开始今天的练习' }).click();
  const started = await (await sessionResponse).json();
  const questions = started.tasks.map((task: { exercise: { id: string } }) =>
    curriculum.exercises.find((q) => q.id === task.exercise.id)!,
  ) as typeof curriculum.exercises;
  expect(questions).toHaveLength(6);
  expect(new Set(questions.map((q) => q.id)).size).toBe(6);
  expect(questions.every((q) => q.lessonId === 'lesson-13' && !q.audioRef)).toBe(true);
  for (const [index, question] of questions.entries()) {
    await expect(page.locator('.play-nav strong')).toHaveText(`第 ${index + 1} / 6 关`);
    await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 15_000 });
    const choice = question.options.findIndex((option) => option.id === question.answer.optionId);
    await optionById(page, question.options[choice]!.id).click();
    if (question.type === 'blend-choice')
      await page.getByRole('button', { name: '确认拼读', exact: true }).click();
    await expect(page.getByText('答对啦！', { exact: true })).toBeVisible();
    if (index === 0) {
      await page.getByRole('button', { name: '听讲解', exact: true }).click();
      await expect(page.getByRole('button', { name: '停止听讲解', exact: true })).toBeVisible();
      await page.getByRole('button', { name: '停止听讲解', exact: true }).click();
    }
    await page.getByRole('button', { name: '继续 →', exact: true }).click();
  }
  await expect(page.getByRole('heading', { name: '今天的探索完成啦！' })).toBeVisible();
  await expect(page.getByLabel('本次练习小结')).toContainText('独立答对：6 题');
  await page.getByRole('button', { name: '回到小岛' }).click();
  const backup = await page.evaluate(async () => {
    const response = await fetch('/api/v1/profiles/export');
    if (!response.ok) throw new Error('family export unavailable');
    return response.json();
  });
  expect(backup.attempts[0].hint_used).toBe(0);
  expect(backup.attempts[0].first_try_correct).toBe(1);
  expect(
    backup.attempts.map((attempt: { exercise_id: string }) => attempt.exercise_id).sort(),
  ).toEqual(questions.map((q) => q.id).sort());
});

test('HINT-VOICE-01: specific hint speaks, retries and replays without independent-answer credit', async ({
  page,
  appUrl,
}) => {
  const hints: string[] = [];
  const answers: string[] = [];
  const media: string[] = [];
  page.on('request', (request) => {
    if (request.url().endsWith('/hint')) hints.push(request.url());
    if (request.url().endsWith('/answer')) answers.push(request.url());
    if (request.url().includes('/voice/hint-')) media.push(request.url());
  });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  const code = (await page.locator('.pair-code').innerText()).match(/[A-Z2-9]{8}/)?.[0];
  expect(code).toBeTruthy();
  await page.getByLabel('家长配对码').fill(code!);
  await page.getByRole('button', { name: '连接家庭' }).click();
  await page.getByRole('button', { name: '开始今天的练习' }).click();
  await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 15_000 });
  expect(media).toEqual([]);
  await page.route('**/api/v1/voice/hint-*', (route) => route.abort('failed'));
  await page.getByRole('button', { name: '给我一点提示' }).click();
  await expect(page.locator('.hint-box')).toContainText('第一声的声调记号是平平的一横');
  await expect(page.getByRole('button', { name: '↻ 重试声音' })).toBeVisible();
  expect(answers).toEqual([]);
  await page.unroute('**/api/v1/voice/hint-*');
  const responsePromise = page.waitForResponse(
    (response) => response.url().includes('/voice/hint-q-01-04') && response.ok(),
  );
  await page.getByRole('button', { name: '↻ 重试声音' }).click();
  await responsePromise;
  await expect(page.getByRole('button', { name: '停止听提示', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '听提示', exact: true })).toBeVisible({
    timeout: 25_000,
  });
  await page.getByRole('button', { name: '听提示', exact: true }).press('Enter');
  await expect(page.getByRole('button', { name: '停止听提示', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '停止听提示', exact: true }).click();
  expect(hints).toHaveLength(1);
  expect(answers).toEqual([]);
  await page.screenshot({ path: test.info().outputPath('spoken-hint.png'), fullPage: true });
  await page.locator('.game-option.hinted').click();
  await expect(page.locator('.feedback')).toContainText('答对啦');
  expect(answers).toHaveLength(1);
  await page.getByRole('button', { name: '退出练习' }).click();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  const downloadPromise = page.waitForEvent('download');
  await page.getByRole('button', { name: '导出家庭数据' }).click();
  const download = await downloadPromise;
  const file = await download.path();
  expect(file).toBeTruthy();
  const saved = JSON.parse(await readFile(file!, 'utf8'));
  const backup = page.getByLabel('导出的 JSON 数据');
  await expect(backup).toBeVisible();
  expect(JSON.parse(await backup.inputValue())).toEqual(saved);
  expect(saved.attempts).toHaveLength(1);
  expect(saved.attempts[0].hint_used).toBe(1);
  expect(saved.attempts[0].first_try_correct).toBe(0);
});
