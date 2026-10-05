import { expect } from '@playwright/test';
import curriculum from '../../content/curriculum.json' with { type: 'json' };
import narration from '../../content/narration.json' with { type: 'json' };
import { optionById } from '../support/options';
import { test } from '../support/real-server';

type Task = { instanceId: string; exercise: { id: string; options: { id: string }[] } };
const scripts = narration.exercises as Record<string, { options: Record<string, string> }>;

for (const guest of [false, true]) {
  test(`OPTION-ORDER-01: ${guest ? 'guest' : 'family'} keeps shuffled order, spoken choice identity and first result`, async ({
    page,
    appUrl,
  }) => {
    test.setTimeout(90_000);
    const errors: string[] = [];
    const submissions: string[] = [];
    page.on('pageerror', (error) => errors.push(error.message));
    page.on('request', (request) => {
      if (request.url().endsWith('/guest/operate')) {
        const operation = request.postDataJSON();
        if (operation.path.endsWith('/answer')) submissions.push(operation.path);
      } else if (request.url().endsWith('/answer')) submissions.push(request.url());
    });
    await page.goto(appUrl);
    if (guest) await page.getByRole('button', { name: '访客体验', exact: true }).click();
    else {
      await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
      await page.getByRole('button', { name: '连接家庭', exact: true }).click();
    }
    const created = page.waitForResponse((response) => {
      if (guest)
        return (
          response.url().endsWith('/guest/operate') &&
          response.request().postDataJSON().path === '/sessions'
        );
      return response.url().endsWith('/sessions') && response.request().method() === 'POST';
    });
    await page.getByRole('button', { name: '开始今天的练习', exact: true }).click();
    const payload = await (await created).json();
    const tasks: Task[] = (guest ? payload.result : payload).tasks;
    const first = tasks[0]!;
    expect(first.instanceId).toMatch(/^op1_[\w-]{24}$/);
    const order = () =>
      page
        .locator('.game-option')
        .evaluateAll((buttons) => buttons.map((button) => button.getAttribute('data-option-id')));
    await expect.poll(order).toEqual(first.exercise.options.map((o) => o.id));
    await page.reload();
    await expect.poll(order).toEqual(first.exercise.options.map((o) => o.id));
    await page.getByRole('button', { name: '听题目', exact: true }).click();
    const authored = curriculum.exercises.find((q) => q.id === first.exercise.id)!;
    const wrong = authored.options.find((o) => o.id !== authored.answer.optionId)!;
    await expect(optionById(page, wrong.id)).toBeEnabled({ timeout: 20_000 });
    await optionById(page, wrong.id).press('Enter');
    await expect(page.locator('.feedback')).toContainText('再选一次');
    await expect(optionById(page, authored.answer.optionId)).toBeEnabled();
    await optionById(page, authored.answer.optionId).click();
    await expect(page.locator('.feedback')).toContainText('找到正确答案');
    expect(submissions).toHaveLength(1);
    await page.getByRole('button', { name: '继续 →', exact: true }).click();

    const spokenIndex = tasks.findIndex(
      (task, index) => index > 0 && Object.keys(scripts[task.exercise.id]!.options).length > 0,
    );
    expect(spokenIndex).toBeGreaterThan(0);
    for (let index = 1; index < spokenIndex; index++) {
      await expect(page.locator('.play-nav strong')).toHaveText(`第 ${index + 1} / 6 关`);
      await page.getByRole('button', { name: '↷ 先跳过这题', exact: true }).click();
    }
    const spoken = tasks[spokenIndex]!;
    await expect.poll(order).toEqual(spoken.exercise.options.map((o) => o.id));
    const firstShownId = spoken.exercise.options[0]!.id;
    const sound = page.waitForResponse(
      (response) =>
        response.url().endsWith(`/voice/option-${spoken.exercise.id}-${firstShownId}`) &&
        [200, 206].includes(response.status()),
    );
    await page.getByRole('button', { name: '听选项 A', exact: true }).click();
    expect((await sound).headers()['content-type']).toMatch(/^audio\//);
    await expect(page.getByRole('button', { name: '停止听选项 A', exact: true })).toBeVisible();
    expect(submissions).toHaveLength(1);
    await page.getByRole('button', { name: '停止听选项 A', exact: true }).click();
    await page.screenshot({
      path: test.info().outputPath('spoken-shuffled-options.png'),
      fullPage: true,
    });
    await page.getByRole('button', { name: '退出练习', exact: true }).click();
    await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeEnabled();
    const backup = guest
      ? await page.evaluate(() => JSON.parse(sessionStorage.getItem('lp.guest.v1')!).state)
      : await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
    expect(backup.attempts).toHaveLength(1);
    expect(JSON.parse(backup.attempts[0].answer_json)).toEqual({ optionId: wrong.id });
    expect(backup.attempts[0].first_try_correct).toBe(0);
    expect(errors).toEqual([]);
  });
}
