import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import reading from '../../content/daily-reading.json' with { type: 'json' };

test.use({ selectedPinyinSource: true });

test('DAILY-01/02: all PDF demonstrations decode and the real reading page follows tones', async ({
  page,
  appUrl,
}) => {
  test.setTimeout(240_000);
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
  expect(items).toHaveLength(840);
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
    { assets: reading.assets.map((a) => a.id), voices },
  );
  expect(decoded).toHaveLength(597 + 42);
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
  await page.getByRole('button', { name: '第 3 份', exact: true }).click();
  await page.getByRole('button', { name: '读词语', exact: false }).click();
  await expect(current).toContainText('中文词句朗读 · 本机音色');
  const voice = page.waitForResponse(
    (r) => r.url().endsWith('/voice/daily-word-day-03-s3-i1') && r.ok(),
  );
  await page.getByRole('button', { name: '开始跟读', exact: false }).click();
  await voice;
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
  await page.screenshot({
    path: `private/daily-asr-${test.info().project.name}.png`,
    fullPage: true,
  });
  await page.getByRole('button', { name: '读过了，下一条' }).click();
  await expect(page.getByLabel('回放我的跟读')).toHaveCount(0);
  await expect(page.locator('.daily-recognition')).toHaveCount(0);
});
