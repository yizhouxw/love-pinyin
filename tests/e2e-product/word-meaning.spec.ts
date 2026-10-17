import { optionById } from '../support/options';
import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import { clearReadingMedia, observeReadingMedia } from '../support/media-log';
import illustrations from '../../content/illustrations.json' with { type: 'json' };
import curriculum from '../../content/curriculum.json' with { type: 'json' };

test.use({ selectedPinyinSource: true });

test('WORD-01: all 84 real picture cards speak, decode and leave no practice events', async ({
  page,
  appUrl,
}) => {
  test.setTimeout(300000);
  await observeReadingMedia(page);
  const external: string[] = [];
  page.on('request', (r) => {
    if (r.url().startsWith('http') && new URL(r.url()).origin !== appUrl) external.push(r.url());
  });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  // Inject before the first image load: WebKit may reuse its decoded image cache on later visits.
  await page.route('**/illustrations/v1-rice.svg*', (r) => r.abort('failed'));
  for (const [id, item] of Object.entries(illustrations.items)) {
    await page
      .getByRole('button', { name: new RegExp(`^${item.lessonId.split('-')[1]} `) })
      .click();
    if (id === 'v1-rice') {
      await expect(page.getByRole('button', { name: '↻ 重试图片' })).toBeVisible();
      await page.getByRole('button', { name: '听图片提示', exact: true }).click();
      await expect(page.getByRole('button', { name: '停止听图片提示', exact: true })).toBeVisible();
      await page.unroute('**/illustrations/v1-rice.svg*');
      await page.getByRole('button', { name: '↻ 重试图片' }).press('Enter');
    }
    const card = page
      .getByRole('region', { name: '生活里的拼音' })
      .locator('.word-card')
      .filter({ has: page.getByRole('img', { name: item.description, exact: true }) });
    const img = card.getByRole('img');
    await expect(img).toHaveAttribute('alt', item.description);
    await expect
      .poll(() => img.evaluate((e: HTMLImageElement) => e.complete && e.naturalWidth > 0))
      .toBe(true);
    await expect(card.locator('figcaption')).toContainText(item.pinyin);
    const spoken = page.waitForResponse((r) => r.url().endsWith(`/voice/picture-${id}`) && r.ok());
    await card.getByRole('button', { name: '听图片说明', exact: true }).click();
    await spoken;
    await expect(card.getByRole('button', { name: '停止听图片说明', exact: true })).toBeVisible();
    const standardSource = `/${'audioKind' in item && item.audioKind === 'daily' ? 'daily-audio' : 'audio'}/${item.audioRef}`;
    await clearReadingMedia(page);
    await card.getByRole('button', { name: '听这个拼音', exact: true }).click();
    // Reused daily clips can play from the Blob pool without another HTTP request.
    await expect
      .poll(() =>
        page.evaluate(
          (source) =>
            window.readingMediaEvents.some(
              (event) => event.type === 'start' && event.source.endsWith(source),
            ),
          standardSource,
        ),
      )
      .toBe(true);
    await expect(card.getByRole('button', { name: '听图片说明', exact: true })).toBeVisible();
    await card.screenshot({ path: test.info().outputPath(`${id}.png`) });
    await page.getByRole('button', { name: '返回学习路线' }).click();
  }
  const ids = [
    'picture-intro',
    'picture-error',
    ...Object.keys(illustrations.items).map((id) => `picture-${id}`),
  ];
  const decoded = await page.evaluate(async (ids) => {
    const ac = new AudioContext();
    const result = [];
    try {
      for (const id of ids) {
        const r = await fetch(`/api/v1/guest/voice/${id}`);
        if (!r.ok) throw Error(id);
        const b = await ac.decodeAudioData(await r.arrayBuffer());
        result.push({
          id,
          duration: b.duration,
          audible: b.getChannelData(0).some((v) => Math.abs(v) > 0.01),
        });
      }
    } finally {
      await ac.close();
    }
    return result;
  }, ids);
  for (const item of decoded) {
    expect(item.duration).toBeGreaterThan(0.1);
    expect(item.audible).toBe(true);
  }
  await page.getByRole('button', { name: /^03 / }).click();
  await page.setViewportSize({ width: 320, height: 850 });
  await page.addStyleTag({ content: 'html {font-size:200% !important}' });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(
    true,
  );
  for (const b of await page.locator('.word-cards button').all())
    expect((await b.boundingBox())!.height).toBeGreaterThanOrEqual(48);
  await page.getByRole('button', { name: '返回学习路线' }).click();
  const state = await page.evaluate(() => JSON.parse(sessionStorage.getItem('lp.guest.v1')!).state);
  expect(state.attempts).toHaveLength(0);
  expect(state.sessions).toHaveLength(0);
  expect(external).toEqual([]);
});

test('WORD-01: picture choices and contextual blending rotate, retry audio and preserve first answers', async ({
  page,
  appUrl,
}) => {
  test.setTimeout(300_000);
  const posts: string[] = [];
  page.on('request', (r) => {
    if (r.url().endsWith('/answer') && r.method() === 'POST') posts.push(r.url());
  });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  const code = (await page.locator('.pair-code').innerText()).match(/[A-Z2-9]{8}/)![0];
  await page.getByLabel('家长配对码').fill(code);
  await page.getByRole('button', { name: '连接家庭' }).click();
  const reached = new Set<string>();
  for (const number of [3, 9, 14]) {
    const lessonId = `lesson-${String(number).padStart(2, '0')}`;
    const wanted = curriculum.exercises.filter(
      (q) => q.lessonId === lessonId && Number(q.id.split('-').at(-1)) >= 150,
    );
    await page.getByRole('button', { name: '家长管理' }).click();
    await page.getByRole('button', { name: '我是家长，继续' }).click();
    await page.getByRole('combobox').selectOption(lessonId);
    const saved = page.waitForResponse(
      (r) => r.url().endsWith('/household/current-lesson') && r.request().method() === 'PUT',
    );
    await page.getByRole('button', { name: '保存', exact: true }).click();
    await saved;
    await page.getByRole('button', { name: '返回学习', exact: true }).click();
    let audioFailed = false;
    if (number === 3) await page.route('**/illustrations/v1-rice.svg*', (r) => r.abort('failed'));
    if (number === 3)
      await page.route('**/audio/audio-rt-03-mi3', (r) => {
        audioFailed = true;
        return r.abort('failed');
      });
    for (let round = 0; round < 12 && !wanted.every((q) => reached.has(q.id)); round++) {
      const created = page.waitForResponse(
        (r) => r.url().endsWith('/sessions') && r.request().method() === 'POST',
      );
      await page.getByRole('button', { name: '开始今天的练习' }).click();
      const session = await (await created).json();
      for (const [i, task] of session.tasks.entries()) {
        await expect(page.locator('.play-nav strong')).toHaveText(`第 ${i + 1} / 6 关`);
        const q = wanted.find((q) => q.id === task.exercise.id);
        if (!q) {
          await page.getByRole('button', { name: '↷ 先跳过这题' }).click();
          continue;
        }
        await expect(page.getByRole('button', { name: '停止听题目', exact: true })).toBeVisible();
        await expect(page.getByRole('button', { name: '听题目', exact: true })).toBeVisible({
          timeout: 20000,
        });
        await page.getByRole('button', { name: '听拼音', exact: true }).press('Enter');
        if (number === 3 && q.id.endsWith('150')) {
          await expect(page.getByRole('button', { name: '↻ 重试声音' })).toBeVisible({
            timeout: 20000,
          });
          expect(audioFailed).toBe(true);
          await expect(page.locator('.game-option').first()).toBeDisabled();
          expect(posts).toHaveLength(0);
          await page.unroute('**/audio/audio-rt-03-mi3');
          await page.getByRole('button', { name: '↻ 重试声音' }).click();
          await expect(page.getByRole('button', { name: '听拼音', exact: true })).toBeVisible({
            timeout: 20000,
          });
          await expect(page.locator('.game-option').first()).toBeDisabled();
          await expect(page.getByRole('button', { name: '↻ 重试图片' })).toBeVisible();
          expect(posts).toHaveLength(0);
          await page.unroute('**/illustrations/v1-rice.svg*');
          await page.getByRole('button', { name: '↻ 重试图片' }).click();
        }
        await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 25000 });
        const correct = q.options.findIndex((o) => o.id === q.answer.optionId);
        if (q.type === 'listen-choice') {
          await expect(page.locator('.game-option img')).toHaveCount(3);
          for (const option of q.options)
            expect(await page.locator('.options').innerText()).not.toContain(option.label);
          const before = posts.length;
          await page.getByRole('button', { name: '听选项 A', exact: true }).click();
          await expect(
            page.getByRole('button', { name: '停止听选项 A', exact: true }),
          ).toBeVisible();
          expect(posts).toHaveLength(before);
          await page.getByRole('button', { name: '停止听选项 A', exact: true }).click();
        } else await expect(page.locator('.word-question-picture img')).toHaveCount(1);
        if (q.id === 'q-03-150') {
          await optionById(page, q.options[(correct + 1) % 3]!.id).press('Enter');
          await expect(page.locator('.feedback')).toContainText('再选一次');
          await expect(optionById(page, q.options[correct]!.id)).toBeEnabled();
        }
        const before = posts.length;
        await optionById(page, q.options[correct]!.id).press('Enter');
        if (q.type === 'blend-choice') {
          expect(posts).toHaveLength(before);
          await expect(page.locator('.blend-preview')).toContainText(q.options[correct]!.label);
          await page.getByRole('button', { name: '确认拼读', exact: true }).press('Enter');
        }
        await expect(page.locator('.feedback')).toContainText(
          q.id === 'q-03-150' ? '找到正确答案啦' : '答对啦',
        );
        await page.screenshot({ path: test.info().outputPath(`${q.id}.png`), fullPage: true });
        reached.add(q.id);
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
  expect(reached.size).toBe(6);
  await page.reload();
  const backup = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
  expect(backup.attempts).toHaveLength(6);
  expect(
    backup.attempts.filter((a: { first_try_correct: number }) => !a.first_try_correct),
  ).toHaveLength(1);
  expect(
    backup.attempts.find((a: { exercise_id: string }) => a.exercise_id === 'q-03-150')
      .first_try_correct,
  ).toBe(0);
  expect(posts).toHaveLength(6);
});
