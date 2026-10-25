import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import { observeReadingMedia, playedReading, clearReadingMedia } from '../support/media-log';
import reading from '../../content/daily-reading.json' with { type: 'json' };

test.use({ selectedPinyinSource: true });

test('DAILY-01/02: all PDF demonstrations decode and the real reading page follows tones', async ({
  page,
  appUrl,
}) => {
  test.setTimeout(240_000);
  await observeReadingMedia(page);
  const external: string[] = [];
  const answers: string[] = [];
  page.on('request', (request) => {
    if (new URL(request.url()).origin !== appUrl) external.push(request.url());
    if (request.url().endsWith('/answer')) answers.push(request.url());
  });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await expect(page.getByRole('heading', { name: '天天练拼音', exact: true })).toBeVisible();
  const status = await page.request.get(`${appUrl}/api/v1/guest/daily-reading`);
  const data = await status.json();
  const items = data.days.flatMap((day: { sections: { items: { available: boolean }[] }[] }) =>
    day.sections.flatMap((section) => section.items),
  );
  expect(items).toHaveLength(785);
  expect(items.every((item: { available: boolean }) => item.available)).toBe(true);
  expect(data.assessment.mode).toBe('asr-syllable-match');
  expect(data.assessment.toneAssessed).toBe(false);
  const voices = reading.days.flatMap((day) =>
    day.sections.flatMap((section) =>
      section.items.filter((item) => item.narrationId).map((item) => item.narrationId!),
    ),
  );
  const decoded = await page.evaluate(
    async ({ assets, voices }) => {
      const context = new AudioContext();
      const result: string[] = [];
      try {
        for (const [kind, ids] of [
          ['daily-audio', assets],
          ['voice', voices],
        ] as const) {
          for (const id of ids) {
            const response = await fetch(`/api/v1/guest/${kind}/${id}`);
            if (!response.ok) throw new Error(`HTTP_${response.status}:${id}`);
            const audio = await context.decodeAudioData(await response.arrayBuffer());
            if (audio.duration < 0.1) throw new Error(`empty:${id}`);
            result.push(id);
          }
        }
        return result;
      } finally {
        await context.close();
      }
    },
    { assets: [...reading.assets.map((a) => a.id), ...reading.derivedAssets], voices },
  );
  expect(decoded).toHaveLength(607 + 10 + 42);
  await page.getByRole('button', { name: '开始第 1 份跟读' }).click();
  const current = page.getByLabel('当前跟读内容');
  await expect(current.getByLabel('ā', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '开始跟读', exact: false }).click();
  await expect(current.getByRole('status')).toHaveText('轮到你读啦，读完点下一条。', {
    timeout: 25000,
  });
  await page.getByRole('button', { name: '读过了，下一条' }).click();
  await expect(current.getByLabel('á', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '连播本节' }).click();
  await expect(page.getByRole('button', { name: '停止示范' })).toBeVisible();
  if (await page.getByRole('button', { name: '换练习', exact: true }).isVisible())
    await page.getByRole('button', { name: '换练习', exact: true }).click();
  await page.getByRole('button', { name: '第 3 份', exact: true }).click();
  await page.getByRole('button', { name: '读词语', exact: false }).click();
  await expect(current).toContainText('中文词句朗读 · 普通话示范');
  await page.getByRole('button', { name: '开始跟读', exact: false }).click();
  await expect
    .poll(async () => (await playedReading(page, 'voice')).includes('daily-word-day-03-s3-i1'), {
      timeout: 25000,
    })
    .toBe(true);
  await expect(current.getByRole('status')).toHaveText('轮到你读啦，读完点下一条。', {
    timeout: 25000,
  });
  await page.screenshot({
    path: `private/daily-reading-${test.info().project.name}.png`,
    fullPage: true,
  });
  expect(answers).toEqual([]);
  expect(external).toEqual([]);
});

test('DAILY-03: microphone refusal stays separate from learning marks and permits direct follow reading', async ({
  page,
  appUrl,
}) => {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia: () => Promise.reject(new DOMException('denied', 'NotAllowedError')) },
    });
  });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: '开始第 1 份跟读' }).click();
  if (
    !(await page.getByRole('button', { name: '录下我的跟读', exact: false }).isVisible()) &&
    !(await page.getByRole('button', { name: '重新录音', exact: false }).isVisible())
  )
    await page.getByText('录音比较（可选）', { exact: true }).click();
  await page.getByRole('button', { name: '录下我的跟读' }).click();
  await expect(page.getByRole('alert')).toContainText('麦克风没有开启', { timeout: 25000 });
  await expect(page.getByLabel('回放我的跟读')).toHaveCount(0);
  await expect(page.getByRole('button', { name: '读过了，下一条' })).toBeEnabled();
  await page.getByText('家长帮助判断', { exact: true }).click();
  await page.getByRole('button', { name: '家长判断：再练一练' }).click();
  await page.getByRole('button', { name: '读过了，下一条' }).click();
  await expect(page.getByLabel('第1份本节内容').getByRole('button').first()).toContainText(
    '家长：再练',
  );
  await page.getByRole('button', { name: '返回小岛' }).click();
  await expect(page.getByRole('button', { name: '进入天天练拼音' })).toBeVisible();
});

test('ASR-04: native browser recording of permitted reference audio reaches local Whisper and shows match / difference', async ({
  page,
  appUrl,
}) => {
  test.setTimeout(120_000);
  // Inject known non-private standard audio into a real MediaRecorder stream.
  // This proves the capture/PCM/API/model/UI chain, not a real child's accuracy.
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: '开始第 1 份跟读' }).click();
  await page.getByRole('button', { name: '开始跟读', exact: false }).click();
  await expect(page.getByLabel('当前跟读内容').getByRole('status')).toHaveText(
    '轮到你读啦，读完点下一条。',
    { timeout: 25000 },
  );
  await page.getByRole('checkbox', { name: '语音引导' }).uncheck();
  const skippedGuides: string[] = [];
  page.on('request', (request) => {
    if (/\/voice\/(daily-ui-record|recognition-)/.test(request.url()))
      skippedGuides.push(request.url());
  });
  await page.evaluate(() => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: async () => {
          const context = new AudioContext();
          const id = (window as unknown as { referenceId?: string }).referenceId ?? 'daily-a1';
          const response = await fetch(`/api/v1/guest/daily-audio/${id}`);
          const source = context.createBufferSource();
          source.buffer = await context.decodeAudioData(await response.arrayBuffer());
          const output = context.createMediaStreamDestination();
          source.connect(output);
          source.start(context.currentTime + 0.15);
          setTimeout(() => {
            void context.close();
          }, 10000);
          return output.stream;
        },
      },
    });
  });
  for (const [id, expected] of [
    ['daily-a1', '电脑识别出的音节和目标相符'],
    ['daily-zhi1', '电脑这次识别成了别的内容'],
  ] as const) {
    await page.evaluate((value) => {
      (window as unknown as { referenceId: string }).referenceId = value;
    }, id);
    if (
      !(await page.getByRole('button', { name: '录下我的跟读', exact: false }).isVisible()) &&
      !(await page.getByRole('button', { name: '重新录音', exact: false }).isVisible())
    )
      await page.getByText('录音比较（可选）', { exact: true }).click();
    await page.getByRole('button', { name: /^(🎙 )?(录下我的跟读|重新录音)$/ }).click();
    await expect(page.getByRole('button', { name: '停止录音' })).toBeVisible({ timeout: 20000 });
    // Wait for the actual MediaRecorder payload, including the complete source syllable.
    await page.waitForTimeout(1400);
    const result = page.waitForResponse(
      (response) =>
        response.url().endsWith('/daily-reading/day-01-s1-i1/recognize') && response.ok(),
    );
    await page.getByRole('button', { name: '停止录音' }).click();
    const response = await result;
    expect((await response.json()).toneAssessed).toBe(false);
    await expect(page.locator('.daily-recognition')).toContainText(expected, { timeout: 15000 });
    await expect(page.locator('.daily-recognition')).toContainText('识别文字：');
    await expect(page.locator('.daily-recognition')).toContainText('不是发音分数');
  }
  expect(skippedGuides).toEqual([]);
  await page.screenshot({
    path: `private/daily-asr-${test.info().project.name}.png`,
    fullPage: true,
  });
  await page.getByRole('button', { name: '读过了，下一条' }).click();
  await expect(page.getByLabel('回放我的跟读')).toHaveCount(0);
  await expect(page.locator('.daily-recognition')).toHaveCount(0);
});

test('DAILY-04: guidance can be skipped, remembered and restored while target audio stays direct', async ({
  page,
  appUrl,
}) => {
  await observeReadingMedia(page);
  const voices = () => playedReading(page, 'voice');
  const targets = () => playedReading(page, 'daily-audio');
  await page.goto(`${appUrl}/#daily-reading`);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  const guidance = page.getByRole('checkbox', { name: '语音引导' });
  await expect(guidance).toBeChecked();
  await page.getByRole('button', { name: '开始第 1 份跟读' }).click();
  await page.getByRole('button', { name: '开始跟读', exact: false }).click();
  await expect
    .poll(async () => (await voices()).some((id) => id.startsWith('daily-instruction-')))
    .toBe(true);
  await guidance.uncheck();
  await expect(page.getByRole('button', { name: '停止示范' })).toHaveCount(0);
  const current = page.getByLabel('当前跟读内容');
  const list = page.getByLabel('第1份本节内容');
  await clearReadingMedia(page);
  await list.getByRole('button').nth(1).click();
  await expect(current.getByLabel('á', { exact: true })).toBeVisible();
  await expect(current.getByRole('status')).toHaveText('轮到你读啦，读完点下一条。');
  expect(await targets()).toEqual(['daily-a2']);
  expect(await voices()).toEqual([]);
  await current.getByRole('button', { name: 'á', exact: true }).click();
  await expect.poll(async () => (await targets()).filter((id) => id === 'daily-a2').length).toBe(2);
  await expect(current.getByRole('status')).toHaveText('轮到你读啦，读完点下一条。');
  await page.getByRole('button', { name: '连播本节' }).click();
  await list.getByRole('button').nth(2).click();
  await expect(current.getByRole('status')).toHaveText('轮到你读啦，读完点下一条。');
  expect((await targets()).at(-1)).toBe('daily-a3');
  expect(await voices()).toEqual([]);
  await page.evaluate(() =>
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: () => Promise.reject(new DOMException('denied', 'NotAllowedError')) },
    }),
  );
  if (
    !(await page.getByRole('button', { name: '录下我的跟读', exact: false }).isVisible()) &&
    !(await page.getByRole('button', { name: '重新录音', exact: false }).isVisible())
  )
    await page.getByText('录音比较（可选）', { exact: true }).click();
  await page.getByRole('button', { name: '录下我的跟读' }).click();
  await expect(page.getByRole('alert')).toContainText('麦克风没有开启');
  expect(await voices()).toEqual([]);
  await page.reload();
  await expect(guidance).not.toBeChecked();
  await page.getByRole('button', { name: '开始第 1 份跟读' }).click();
  await guidance.check();
  await clearReadingMedia(page);
  await current.getByRole('button', { name: 'ā', exact: true }).click();
  await expect(current.getByRole('status')).toHaveText('轮到你读啦，读完点下一条。', {
    timeout: 25000,
  });
  expect([...new Set(await voices())]).toEqual([
    `daily-instruction-${reading.days[0]!.sections[0]!.id}`,
    'daily-ui-follow',
  ]);
});

test('DAILY-05: parent opt-out reaches daily practice and nearby shortcuts share one preference', async ({
  page,
  appUrl,
}) => {
  // An old default-on daily preference must never bypass the family opt-out.
  await page.addInitScript(() => {
    if (!localStorage.getItem('love-pinyin.guidance'))
      localStorage.setItem('love-pinyin.daily-guidance', 'on');
  });
  await observeReadingMedia(page);
  const instructions = async () =>
    (await playedReading(page, 'voice')).filter((id) => /^daily-(instruction-|ui-follow)/.test(id));
  const entry = await page.goto(appUrl);
  expect(entry?.headers()['cache-control']).toBe('no-store');
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  const code = (await page.locator('.pair-code').innerText()).match(/[A-Z2-9]{8}/)?.[0];
  await page.getByLabel('家长配对码').fill(code!);
  await page.getByRole('button', { name: '连接家庭' }).click();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await page.getByText('声音与播放设置', { exact: true }).click();
  await page.getByRole('checkbox', { name: '自动朗读题目', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: '自动朗读题目', exact: true })).not.toBeChecked();
  await expect(page.getByRole('checkbox', { name: '自动朗读题目', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '返回学习', exact: true }).click();
  const shortcut = page.getByRole('checkbox', { name: '语音引导', exact: true });
  await expect(shortcut).not.toBeChecked();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: '开始第 1 份跟读' }).click();
  const reader = page.getByLabel('当前跟读内容');
  await expect(reader.getByRole('checkbox', { name: '语音引导', exact: true })).not.toBeChecked();
  await page.getByRole('button', { name: '开始跟读', exact: false }).click();
  await expect(reader.getByRole('status')).toHaveText('轮到你读啦，读完点下一条。');
  expect(await instructions()).toEqual([]);
  await shortcut.check();
  await reader.getByRole('button', { name: 'ā', exact: true }).click();
  await expect.poll(async () => (await instructions()).length).toBeGreaterThan(0);
  await shortcut.uncheck();
  await expect(page.getByRole('button', { name: '停止示范' })).toHaveCount(0);
  await expect(reader.getByRole('alert')).toHaveCount(0);
  await page.evaluate(() => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: { getUserMedia: () => Promise.reject(new DOMException('denied', 'NotAllowedError')) },
    });
  });
  await shortcut.check();
  if (
    !(await page.getByRole('button', { name: '录下我的跟读', exact: false }).isVisible()) &&
    !(await page.getByRole('button', { name: '重新录音', exact: false }).isVisible())
  )
    await page.getByText('录音比较（可选）', { exact: true }).click();
  await page.getByRole('button', { name: '录下我的跟读' }).click();
  await shortcut.uncheck();
  await expect(reader.getByRole('alert')).toContainText('麦克风没有开启');
  await page.screenshot({
    path: `private/shared-guidance-${test.info().project.name}.png`,
    fullPage: true,
  });
  await page.getByRole('button', { name: '返回小岛' }).click();
  await expect(shortcut).not.toBeChecked();
  await page.reload();
  await expect(shortcut).not.toBeChecked();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await page.getByText('声音与播放设置', { exact: true }).click();
  await page.getByRole('checkbox', { name: '自动朗读题目', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: '自动朗读题目', exact: true })).toBeChecked();
  await expect(page.getByRole('checkbox', { name: '自动朗读题目', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '返回学习', exact: true }).click();
  await expect(shortcut).toBeChecked();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await expect(shortcut).toBeChecked();
});

test('UX-04/05: practice keeps material choices and recording out of the main flow', async ({
  page,
  appUrl,
}) => {
  await observeReadingMedia(page);
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: '开始第 1 份跟读' }).click();
  const reader = page.getByLabel('当前跟读内容');
  await expect(page.getByRole('navigation', { name: '选择每日练习' })).toHaveCount(0);
  await expect(reader.getByRole('button', { name: '录下我的跟读' })).not.toBeVisible();
  const strip = reader.locator('.daily-status-strip');
  const before = await strip.boundingBox();
  await page.getByLabel('第1份本节内容').getByRole('button').nth(1).click();
  await expect
    .poll(async () => (await playedReading(page, 'daily-audio')).includes('daily-a2'), {
      timeout: 25000,
    })
    .toBe(true);
  await expect(reader.getByRole('status')).toContainText('轮到你读啦', { timeout: 25000 });
  expect((await strip.boundingBox())?.height).toBe(before?.height);
  await reader.getByRole('button', { name: '连播本节' }).click();
  await expect(reader.getByRole('button', { name: '停止示范' })).toBeVisible();
  await reader.getByRole('button', { name: '停止示范' }).click();
  expect((await strip.boundingBox())?.height).toBe(before?.height);
  await reader.getByText('录音比较（可选）', { exact: true }).click();
  await expect(reader.getByRole('button', { name: '录下我的跟读' })).toBeVisible();
  await page.getByRole('button', { name: '换练习', exact: true }).click();
  await expect(page.getByRole('navigation', { name: '选择每日练习' })).toBeVisible();
});
