import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import writing from '../../content/writing.json' with { type: 'json' };
import curriculum from '../../content/curriculum.json' with { type: 'json' };

test.use({ selectedPinyinSource: true });

test('WRITE-01: actual handwriting voice, stroke controls, audio exclusivity and no fake scores', async ({
  page,
  appUrl,
}) => {
  test.setTimeout(150_000);
  const external: string[] = [];
  page.on('request', (r) => {
    if (r.url().startsWith('http') && new URL(r.url()).origin !== appUrl) external.push(r.url());
  });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '听本课录音' }).click();
  await page.getByRole('button', { name: '播放课程录音', exact: true }).click();
  await expect
    .poll(() => page.getByLabel('课程录音播放进度').evaluate((e: HTMLAudioElement) => e.paused))
    .toBe(false);
  const intro = page.waitForResponse((r) => r.url().endsWith('/voice/writing-ui-intro') && r.ok());
  await page.getByRole('button', { name: '打开书写课堂' }).press('Enter');
  await intro;
  await expect
    .poll(() => page.getByLabel('课程录音播放进度').evaluate((e: HTMLAudioElement) => e.paused))
    .toBe(true);
  await expect(page.getByRole('button', { name: '停止听书写玩法' })).toBeVisible();
  await page.getByRole('button', { name: '看第一笔' }).press('Enter');
  await expect(page.locator('.writing-instruction')).toContainText('第 1 / 2 笔');
  await expect(page.locator('.writing-stage .active')).toHaveCount(1);
  await expect(page.locator('.writing-stage .future')).toHaveCount(1);
  await expect(page.getByRole('button', { name: '看上一笔' })).toBeDisabled();
  await expect(page.getByRole('button', { name: '听当前步骤', exact: true })).toBeVisible({
    timeout: 20000,
  });
  await page.getByRole('button', { name: '看下一笔' }).press('Enter');
  await expect(page.locator('.writing-instruction')).toContainText('第 2 / 2 笔');
  await expect(page.getByRole('button', { name: '看下一笔' })).toBeDisabled();
  await page.getByRole('button', { name: '看上一笔' }).click();
  await expect(page.locator('.writing-instruction')).toContainText('第 1 / 2 笔');
  await page.getByRole('button', { name: '看完整字形' }).click();
  await expect(page.locator('.writing-stage .future')).toHaveCount(0);
  await page.getByRole('button', { name: '观察 e 的书写', exact: true }).click();
  await expect(page.getByRole('button', { name: '停止听e占格', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await page.getByRole('button', { name: '看第一笔' }).click();
  await expect(page.locator('.writing-instruction')).toContainText('先向右写横');
  await page.route('**/voice/writing-ui-paper', (r) => r.abort('failed'));
  await page.getByRole('button', { name: '听纸笔练习', exact: true }).click();
  await expect(page.getByRole('button', { name: '↻ 重试声音' })).toBeVisible();
  await page.unroute('**/voice/writing-ui-paper');
  await page.getByRole('button', { name: '↻ 重试声音' }).click();
  await expect(page.getByRole('button', { name: '停止听纸笔练习' })).toBeVisible();
  await page.getByRole('button', { name: '停止听纸笔练习' }).click();
  // Actual files, not synthetic tones; every step and placement is decoded.
  const ids = ['writing-ui-intro', 'writing-ui-paper', 'writing-ui-full', 'writing-ui-choose'];
  for (const [id, g] of Object.entries(writing.glyphs)) {
    ids.push(`writing-${id}-placement`);
    g.strokes.forEach((_, i) => ids.push(`writing-${id}-stroke-${i + 1}`));
  }
  const decoded = await page.evaluate(async (ids) => {
    const ac = new AudioContext();
    const result = [];
    try {
      for (const id of ids) {
        const r = await fetch(`/api/v1/guest/voice/${id}`);
        if (!r.ok) throw new Error(id);
        const b = await ac.decodeAudioData(await r.arrayBuffer());
        let peak = 0;
        for (const s of b.getChannelData(0)) peak = Math.max(peak, Math.abs(s));
        result.push({ id, duration: b.duration, peak });
      }
    } finally {
      await ac.close();
    }
    return result;
  }, ids);
  for (const r of decoded) {
    expect(r.duration, r.id).toBeGreaterThan(0.1);
    expect(r.peak, r.id).toBeGreaterThan(0.01);
  }
  await page
    .locator('.writing-workshop')
    .screenshot({ path: test.info().outputPath('writing-classroom.png') });
  await page.setViewportSize({ width: 320, height: 850 });
  await page.addStyleTag({ content: 'html {font-size:200% !important}' });
  await expect
    .poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1))
    .toBe(true);
  for (const button of await page.locator('.writing-workshop button:visible').all()) {
    const box = await button.boundingBox();
    expect(box!.height).toBeGreaterThanOrEqual(48);
  }
  await page
    .locator('.writing-stage')
    .screenshot({ path: test.info().outputPath('writing-e.png') });
  await page.getByRole('button', { name: '返回学习路线' }).click();
  const state = await page.evaluate(() => JSON.parse(sessionStorage.getItem('lp.guest.v1')!).state);
  expect(state.attempts).toHaveLength(0);
  expect(state.sessions).toHaveLength(0);
  expect(external).toEqual([]);
});

test('WRITE-01: graphical grid questions are reached and stored through real lesson rotation', async ({
  page,
  appUrl,
}) => {
  test.setTimeout(180_000);
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  const code = (await page.locator('.pair-code').innerText()).match(/[A-Z2-9]{8}/)![0];
  await page.getByLabel('家长配对码').fill(code);
  await page.getByRole('button', { name: '连接家庭' }).click();
  const reached: string[] = [];
  for (const lessonId of ['lesson-01', 'lesson-03', 'lesson-06']) {
    await page.getByRole('button', { name: '家长管理' }).click();
    await page.getByRole('button', { name: '我是家长，继续' }).click();
    await page.getByRole('combobox').selectOption(lessonId);
    const saved = page.waitForResponse(
      (r) => r.url().endsWith('/household/current-lesson') && r.request().method() === 'PUT',
    );
    await page.getByRole('button', { name: '保存', exact: true }).click();
    await saved;
    await page.getByRole('button', { name: '返回学习', exact: true }).click();
    const wanted = curriculum.exercises.find(
      (q) => q.lessonId === lessonId && q.options.some((o) => 'writing' in o),
    )!;
    for (let round = 0; round < 10 && !reached.includes(wanted.id); round++) {
      const created = page.waitForResponse(
        (r) => r.url().endsWith('/sessions') && r.request().method() === 'POST',
      );
      await page.getByRole('button', { name: '开始今天的练习' }).click();
      const session = await (await created).json();
      for (const [i, t] of session.tasks.entries()) {
        await expect(page.locator('.play-nav strong')).toHaveText(`第 ${i + 1} / 6 关`);
        if (t.exercise.id !== wanted.id) {
          await page.getByRole('button', { name: '↷ 先跳过这题' }).click();
          continue;
        }
        await expect(page.locator('.writing-option')).toHaveCount(3);
        await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 20000 });
        await page
          .locator('.game-option')
          .nth(wanted.options.findIndex((o) => o.id === wanted.answer.optionId))
          .press('Enter');
        await expect(page.locator('.feedback')).toContainText('答对啦');
        await page.screenshot({ path: test.info().outputPath(`${wanted.id}.png`), fullPage: true });
        reached.push(wanted.id);
        await page.getByRole('button', { name: '继续 →', exact: true }).click();
      }
      const finished = page.waitForResponse((r) =>
        r.url().endsWith(`/sessions/${session.id}/finish`),
      );
      await page.getByRole('button', { name: '回到小岛' }).click();
      if ((await (await finished).json()).breakRequired)
        await page.getByRole('button', { name: '休息好了，继续学习' }).click();
    }
  }
  expect(reached).toHaveLength(3);
  await page.reload();
  const backup = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
  expect(backup.attempts).toHaveLength(3);
  expect(
    backup.attempts.every((a: { first_try_correct: number }) => a.first_try_correct === 1),
  ).toBe(true);
});

test('WRITE-01: all authored course targets render in order, including single-storey g and ü', async ({
  page,
  appUrl,
}) => {
  test.setTimeout(120_000);
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  for (const [lessonId, targets] of Object.entries(writing.lessons)) {
    const number = lessonId.split('-')[1];
    await page.getByRole('button', { name: new RegExp(`^${number} `) }).click();
    await page.getByRole('button', { name: '打开书写课堂' }).click();
    await expect(page.getByRole('group', { name: '选择书写目标' }).getByRole('button')).toHaveCount(
      targets.length,
    );
    for (const target of targets) {
      await page.getByRole('button', { name: `观察 ${target.label} 的书写`, exact: true }).click();
      const count = target.glyphIds.reduce(
        (sum, id) => sum + writing.glyphs[id as keyof typeof writing.glyphs].strokes.length,
        0,
      );
      await expect(page.locator('.writing-stage [data-stroke]')).toHaveCount(count);
      await expect(page.locator('.writing-instruction')).toContainText(`${count} 笔 · 完整字形`);
      if (target.label.length === 1)
        await page.locator('.writing-stage').screenshot({
          path: test.info().outputPath(`glyph-${target.label === 'ü' ? 'v' : target.label}.png`),
        });
    }
    await page.getByRole('button', { name: '看第一笔' }).click();
    await expect(page.locator('.writing-stage .active')).toHaveCount(1);
    await page.getByRole('button', { name: '返回学习路线' }).click();
  }
  const state = await page.evaluate(() => JSON.parse(sessionStorage.getItem('lp.guest.v1')!).state);
  expect(state.attempts).toHaveLength(0);
});
