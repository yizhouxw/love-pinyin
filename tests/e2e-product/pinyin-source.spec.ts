import { expect } from '@playwright/test';
import curriculum from '../../content/curriculum.json' with { type: 'json' };
import source from '../../content/pinyin-source.json' with { type: 'json' };
import { test } from '../support/real-server';

test.use({ selectedPinyinSource: true });

test('SOURCE-01: actual selected audio decodes, plays and completes a local listening round', async ({
  page,
  appUrl,
}) => {
  const external: string[] = [];
  const answers: string[] = [];
  page.on('request', (request) => {
    if (request.url().startsWith('http') && new URL(request.url()).origin !== appUrl)
      external.push(request.url());
    if (request.url().endsWith('/answer')) answers.push(request.url());
  });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  const code = (await page.locator('.pair-code').innerText()).match(/[A-Z2-9]{8}/)?.[0];
  expect(code).toBeTruthy();
  await page.getByLabel('家长配对码').fill(code!);
  await page.getByRole('button', { name: '连接家庭' }).click();
  await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeVisible();
  const decoded = await page.evaluate(
    async (ids) => {
      const audio = new AudioContext();
      const results: { id: string; seconds: number; peak: number }[] = [];
      try {
        for (const id of ids) {
          const response = await fetch(`/api/v1/audio/${id}`);
          if (!response.ok) throw new Error(`${id}: ${response.status}`);
          const buffer = await audio.decodeAudioData(await response.arrayBuffer());
          const samples = buffer.getChannelData(0);
          let peak = 0;
          for (const sample of samples) peak = Math.max(peak, Math.abs(sample));
          results.push({ id, seconds: buffer.duration, peak });
        }
        return results;
      } finally {
        await audio.close();
      }
    },
    source.assets.map((a) => a.id),
  );
  expect(decoded).toHaveLength(source.assets.length);
  for (const result of decoded) {
    expect(result.seconds, result.id).toBeGreaterThan(0.1);
    expect(result.seconds, result.id).toBeLessThan(10);
    expect(result.peak, result.id).toBeGreaterThan(0.01);
  }
  await page.getByRole('button', { name: '听本课录音' }).click();
  await page.getByRole('button', { name: 'a 播放标准音', exact: true }).click();
  await expect(page.getByRole('button', { name: 'a 停止播放', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'a 停止播放', exact: true }).click();
  await page.getByRole('button', { name: 'a 播放标准音', exact: true }).press('Enter');
  await expect(page.getByRole('button', { name: 'a 停止播放', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '返回学习路线' }).click();
  expect(answers).toEqual([]);
  const started = page.waitForResponse(
    (r) => r.url().endsWith('/sessions') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: '开始今天的练习' }).click();
  const session = await (await started).json();
  const questions = session.tasks.map((task: { exercise: { id: string } }) =>
    curriculum.exercises.find((q) => q.id === task.exercise.id)!,
  ) as typeof curriculum.exercises;
  expect(questions).toHaveLength(6);
  expect(questions.some((q) => q.type === 'listen-choice')).toBe(true);
  for (const [index, question] of questions.entries()) {
    await expect(page.locator('.play-nav strong')).toHaveText(`第 ${index + 1} / 6 关`);
    if (question.audioRef) {
      await expect(page.locator('.game-option').first()).toBeDisabled();
      // Finish actual instruction before testing the separate pronunciation recording.
      await expect(page.getByRole('button', { name: '停止听题目', exact: true })).toBeVisible();
      await expect(page.getByRole('button', { name: '听题目', exact: true })).toBeVisible({
        timeout: 20000,
      });
      if (index === 0) {
        await page.route(`**/api/v1/audio/${question.audioRef}`, (route) => route.abort('failed'));
        await page.getByRole('button', { name: '听拼音', exact: true }).click();
        await expect(page.getByRole('button', { name: '↻ 重试声音' })).toBeVisible();
        await expect(page.locator('.game-option').first()).toBeDisabled();
        expect(answers).toEqual([]);
        await page.unroute(`**/api/v1/audio/${question.audioRef}`);
        await page.getByRole('button', { name: '↻ 重试声音' }).click();
      } else await page.getByRole('button', { name: '听拼音', exact: true }).click();
    }
    await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 20000 });
    if (index === 0)
      await page.screenshot({ path: test.info().outputPath('real-listening.png'), fullPage: true });
    const choice = question.options.findIndex((o) => o.id === question.answer.optionId);
    await page.locator('.game-option').nth(choice).click();
    if (question.type === 'blend-choice')
      await page.getByRole('button', { name: '确认拼读', exact: true }).click();
    await expect(page.locator('.feedback')).toContainText('答对啦');
    await page.getByRole('button', { name: '继续 →', exact: true }).click();
  }
  await expect(page.getByLabel('本次练习小结')).toContainText('独立答对：6 题');
  await page.getByRole('button', { name: '回到小岛' }).click();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await expect(page.getByLabel('学习音频准备状态')).toContainText(
    `${source.assets.length} 项可播放`,
  );
  await expect(page.getByLabel('学习音频准备状态')).toContainText('标准音来源：cmguo/PinYinSound');
  await expect(page.getByText(/教师审校|待审音|审核者|课程草稿/)).toHaveCount(0);
  const exported = await page.request.get(`${appUrl}/api/v1/profiles/export`);
  const backup = await exported.json();
  expect(answers).toHaveLength(6);
  expect(backup.attempts.map((a: { exercise_id: string }) => a.exercise_id).sort()).toEqual(
    questions.map((q) => q.id).sort(),
  );
  expect(
    backup.attempts.every((a: { first_try_correct: number }) => a.first_try_correct === 1),
  ).toBe(true);
  expect(external).toEqual([]);
});
