import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import curriculum from '../../content/curriculum.json' with { type: 'json' };
import { optionById } from '../support/options';

test.use({ selectedPinyinSource: true });

for (const guidance of [false, true]) {
  test(`ANSWER-READY-02: y/w requires only standard audio with guidance ${guidance}`, async ({
    page,
    appUrl,
  }) => {
    const answers: string[] = [];
    page.on('request', (request) => {
      if (request.url().endsWith('/answer')) answers.push(request.url());
    });
    await page.goto(appUrl);
    await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
    const code = (await page.locator('.pair-code').innerText()).match(/[A-Z2-9]{8}/)![0];
    await page.getByLabel('家长配对码').fill(code);
    await page.getByRole('button', { name: '连接家庭' }).click();
    await page.getByRole('button', { name: '家长管理' }).click();
    await page.getByRole('button', { name: '我是家长，继续' }).click();
    await page.getByRole('combobox').selectOption('lesson-09');
    await page.getByRole('button', { name: '保存', exact: true }).click();
    await page.getByRole('button', { name: '返回学习', exact: true }).click();
    await page.getByRole('checkbox', { name: '语音引导', exact: true }).setChecked(guidance);
    const created = page.waitForResponse(
      (response) => response.url().endsWith('/sessions') && response.request().method() === 'POST',
    );
    await page.getByRole('button', { name: '开始今天的练习' }).click();
    const session = await (await created).json();
    const first = session.tasks[0].exercise;
    expect(first.lessonId).toBe('lesson-09');
    expect(first.audioRef).toBeTruthy();
    const option = page.locator('.game-option').first();
    const status = page.locator('#answer-availability');
    await expect(status).toContainText('请点“听拼音”');
    await expect(option).toBeDisabled();
    await expect(option).toHaveAttribute('aria-describedby', 'answer-availability');
    if (await page.getByRole('button', { name: '停止听题目', exact: true }).count())
      await page.getByRole('button', { name: '停止听题目', exact: true }).click();
    // A failed optional prompt cannot replace the real standard-audio requirement.
    await page.route('**/api/v1/voice/prompt-*', (route) => route.abort('failed'));
    await page.getByRole('button', { name: '听题目', exact: true }).click();
    await expect(page.getByRole('button', { name: '↻ 重试声音' })).toBeVisible();
    await expect(option).toBeDisabled();
    // An incomplete first standard sample does not satisfy the gate.
    await page.getByRole('button', { name: '听拼音', exact: true }).click();
    await page.getByRole('button', { name: '停止听拼音', exact: true }).click();
    await expect(option).toBeDisabled();
    await page.getByRole('button', { name: '听拼音', exact: true }).click();
    await expect(option).toBeEnabled({ timeout: 20000 });
    await expect(status).toHaveText('可以选择答案了。');
    // Even a failed prompt replay cannot relock a fully heard standard sample.
    await page.getByRole('button', { name: '听题目', exact: true }).click();
    await expect(page.getByRole('button', { name: '↻ 重试声音' })).toBeVisible();
    await expect(option).toBeEnabled();
    await page.unroute('**/api/v1/voice/prompt-*');
    // Optional narration remains available but never controls answer availability.
    await page.getByRole('button', { name: '听题目', exact: true }).click();
    await page.getByRole('button', { name: '停止听题目', exact: true }).click();
    await expect(option).toBeEnabled();
    await page.getByRole('button', { name: '听拼音', exact: true }).click();
    await page.getByRole('button', { name: '停止听拼音', exact: true }).click();
    await expect(option).toBeEnabled();
    expect(answers).toEqual([]);
    const reference = curriculum.exercises.find((question) => question.id === first.id)!;
    await optionById(page, reference.answer.optionId!).click();
    await expect(page.locator('.feedback')).toContainText('答对啦');
    await expect(status).toContainText('这题已经完成');
    await page.getByRole('button', { name: '继续 →', exact: true }).click();
    await expect(option).toBeDisabled();
    await expect(status).toContainText('听拼音');
    expect(answers).toHaveLength(1);
    const visualIndex = session.tasks.findIndex(
      (task: { exercise: { audioRef?: string } }, index: number) =>
        index > 0 && !task.exercise.audioRef,
    );
    expect(visualIndex).toBeGreaterThan(0);
    for (let index = 1; index < visualIndex; index++) {
      await page.getByRole('button', { name: '先跳过这题' }).click();
      await expect(page.locator('.play-nav strong')).toHaveText(
        `第 ${index + 2} / ${session.tasks.length} 关`,
      );
    }
    // Visual tasks are immediately answerable even if guidance is off or still playing.
    await expect(option).toBeEnabled();
    await expect(status).toHaveText('可以选择答案了。');
    const visual = curriculum.exercises.find(
      (question) => question.id === session.tasks[visualIndex].exercise.id,
    )!;
    await optionById(page, visual.answer.optionId!).click();
    if (visual.type === 'blend-choice')
      await page.getByRole('button', { name: '确认拼读', exact: true }).click();
    await expect(page.locator('.feedback')).toContainText('答对啦');
    expect(answers).toHaveLength(2);
    await page.screenshot({
      path: test.info().outputPath('yw-answer-readiness.png'),
      fullPage: true,
    });
  });
}
