import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import curriculum from '../../content/curriculum.json' with { type: 'json' };

for (const { knowledgeId, symbol, slice } of [
  { knowledgeId: 'k-letter-y', symbol: 'y', slice: 'BANK-02' },
  { knowledgeId: 'k-initial-zh', symbol: 'zh', slice: 'BANK-03' },
  { knowledgeId: 'k-final-ve', symbol: 'üe', slice: 'BANK-03' },
]) {
  test(`${slice}: ${symbol} completes a real spoken two-task review`, async ({
    page,
    appUrl,
    seedReview,
  }) => {
    await page.goto(appUrl);
    await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
    const code = (await page.locator('.pair-code').innerText()).match(/[A-Z2-9]{8}/)?.[0];
    expect(code).toBeTruthy();
    await page.getByLabel('家长配对码').fill(code!);
    await page.getByRole('button', { name: '连接家庭' }).click();
    await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeVisible();
    // Only historical due-state is seeded in this fixture's temporary SQLite.
    // Course, question selection, sounds, answers and finish use actual services.
    await seedReview(knowledgeId);
    await page.reload();
    const recommendation = page.getByRole('region', { name: '今日推荐复习' });
    await expect(recommendation).toContainText(symbol);
    const created = page.waitForResponse(
      (r) =>
        r.url().endsWith(`/reviews/${knowledgeId}/sessions`) && r.request().method() === 'POST',
    );
    await recommendation.getByRole('button').click();
    const session = await (await created).json();
    expect(session.tasks).toHaveLength(2);
    expect(
      new Set(session.tasks.map((t: { exercise: { id: string } }) => t.exercise.id)).size,
    ).toBe(2);
    if (slice === 'BANK-03') {
      expect(
        session.tasks.some(
          (task: { exercise: { id: string } }) => Number(task.exercise.id.split('-').at(-1)) >= 40,
        ),
      ).toBe(true);
    }
    for (let i = 0; i < 2; i++) {
      const q = curriculum.exercises.find((q) => q.id === session.tasks[i].exercise.id)!;
      expect(q.primaryKnowledgeId).toBe(knowledgeId);
      await expect(page.locator('.play-nav strong')).toHaveText(`第 ${i + 1} / 2 关`);
      await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 20000 });
      const answerIndex = q.options.findIndex((o) => o.id === q.answer.optionId);
      await page.locator('.game-option').nth(answerIndex).click();
      await expect(page.locator('.feedback')).toContainText('答对啦');
      await page.getByRole('button', { name: '继续 →', exact: true }).click();
    }
    await expect(page.getByRole('heading', { name: '今天的探索完成啦！' })).toBeVisible();
    await expect(page.getByLabel('本次练习小结')).toContainText('独立答对：2 题');
    await page.getByRole('button', { name: '回到小岛', exact: true }).click();
    await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeVisible();
    const saved = await page.request.get(`${appUrl}/api/v1/profiles/export`);
    expect(saved.ok()).toBe(true);
    const backup = await saved.json();
    expect(backup.attempts).toHaveLength(2);
    expect(backup.sessions).toHaveLength(1);
    expect(backup.sessions[0].status).toBe('finished');
    expect(
      backup.attempts.every(
        (a: { knowledge_id: string; first_try_correct: number }) =>
          a.knowledge_id === knowledgeId && a.first_try_correct === 1,
      ),
    ).toBe(true);
  });
}
