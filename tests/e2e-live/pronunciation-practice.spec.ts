import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import { pairForHouseholdMaterial, useHouseholdMaterial } from '../support/household-material';
import { documentTop } from '../support/interaction';

test.use({ selectedPinyinSource: true });

// Synthetic capture proves native MediaRecorder -> PCM -> same-origin API only.
// It is not evidence about pronunciation quality, children or physical devices.
async function installCapture(page: import('@playwright/test').Page) {
  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: async () => {
          const context = new AudioContext();
          const source = context.createOscillator();
          const output = context.createMediaStreamDestination();
          source.connect(output);
          source.start();
          const track = output.stream.getAudioTracks()[0]!;
          const stop = track.stop.bind(track);
          track.stop = () => {
            stop();
            source.stop();
            void context.close();
          };
          (window as unknown as { lastCaptureStream: MediaStream }).lastCaptureStream =
            output.stream;
          return output.stream;
        },
      },
    });
  });
}

async function guest(page: import('@playwright/test').Page, url: string) {
  await page.goto(url);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
}

test('MATCH-16: course demonstration and local-only replay are separate', async ({
  page,
  appUrl,
}) => {
  await installCapture(page);
  const uploads: string[] = [];
  page.on('request', (request) => {
    if (request.method() === 'POST' && request.headers()['content-type']?.startsWith('audio/'))
      uploads.push(request.url());
  });
  await guest(page, appUrl);
  await page.getByRole('checkbox', { name: '语音引导' }).uncheck();
  if (await page.getByRole('button', { name: '完成', exact: true }).isVisible())
    await page.getByRole('button', { name: '完成', exact: true }).click();
  await page.getByRole('button', { name: '课堂学习' }).click();
  const course = page.getByRole('region', { name: '课程拼读跟读' });
  const record = course.getByRole('button', { name: '录下我的跟读' });
  await expect(record).toBeHidden();
  const demo = page.waitForResponse(
    (response) => response.url().includes('/audio/') && response.ok(),
  );
  await course.getByRole('button', { name: '听示范' }).click();
  expect((await demo).headers()['content-type']).toMatch(/^audio\//);
  await course.getByText('录音回放（可选）', { exact: false }).click();
  await expect(course.getByText('课程拼读识别暂未启用。', { exact: false })).toBeVisible();
  await record.click();
  const stop = course.getByRole('button', { name: '停止录音', exact: false });
  await expect(stop).toBeVisible();
  await page.waitForTimeout(1000);
  await stop.click();
  const replay = page.getByLabel('回放课程跟读');
  await expect(replay).toHaveAttribute('src', /^blob:/);
  await course
    .getByRole('navigation', { name: '选择跟读目标' })
    .getByRole('button', { name: 'é', exact: true })
    .click();
  await expect(replay).toHaveCount(0);
  await expect(record).toBeHidden();
  await page.getByRole('button', { name: '返回学习路线' }).click();
  await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeEnabled();
  expect(uploads).toEqual([]);
});

test('SHOP-09: daily capture is local and can be confirmed by a parent before model installation', async ({
  page,
  appUrl,
}) => {
  await installCapture(page);
  await pairForHouseholdMaterial(page, appUrl);
  await useHouseholdMaterial(page);
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: '开始第 1 份跟读' }).click();
  await page.getByText('播放设置', { exact: true }).click();
  await page.getByRole('checkbox', { name: '语音引导' }).uncheck();
  if (await page.getByRole('button', { name: '完成', exact: true }).isVisible())
    await page.getByRole('button', { name: '完成', exact: true }).click();
  await page.getByText('录音比较（可选）', { exact: true }).click();
  const adult = page.getByText('家长帮助判断', { exact: true });
  const adultTop = await documentTop(adult);
  await page.getByRole('button', { name: '录下我的跟读' }).click();
  const stop = page.getByRole('button', { name: '停止录音', exact: false });
  await expect(stop).toBeVisible();
  await page.waitForTimeout(1000);
  const uploads: string[] = [];
  page.on('request', (request) => {
    if (/\/(recognize|assess)$/.test(request.url())) uploads.push(request.url());
  });
  await stop.click();
  await expect(page.getByLabel('回放我的跟读')).toBeVisible();
  expect(await documentTop(adult)).toBe(adultTop);
  await expect(page.getByText('请听回放，用下方的家长判断确认本条跟读。')).toBeVisible();
  await expect(page.getByRole('button', { name: '重新识别这段跟读' })).toHaveCount(0);
  await adult.click();
  await page.getByRole('button', { name: '家长判断：熟练' }).click();
  await expect(page.getByRole('button', { name: '家长判断：熟练' })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await expect(page.getByRole('button', { name: '读过了，下一条' })).toBeEnabled();
  await page.getByRole('button', { name: '清除这段录音' }).click();
  expect(uploads).toEqual([]);
  await expect(page.getByLabel('回放我的跟读')).toHaveCount(0);
});

test('MATCH-15: microphone refusal leaves the course usable and creates no recognition request', async ({
  page,
  appUrl,
}) => {
  await page.addInitScript(() =>
    Object.defineProperty(navigator, 'mediaDevices', {
      value: { getUserMedia: () => Promise.reject(new DOMException('denied', 'NotAllowedError')) },
    }),
  );
  const recognitionRequests: string[] = [];
  page.on('request', (request) => {
    if (request.url().endsWith('/assess')) recognitionRequests.push(request.url());
  });
  await guest(page, appUrl);
  await page.getByRole('checkbox', { name: '语音引导' }).uncheck();
  if (await page.getByRole('button', { name: '完成', exact: true }).isVisible())
    await page.getByRole('button', { name: '完成', exact: true }).click();
  await page.getByRole('button', { name: '课堂学习' }).click();
  const course = page.getByRole('region', { name: '课程拼读跟读' });
  await course.getByText('录音回放（可选）', { exact: false }).click();
  await course.getByRole('button', { name: '录下我的跟读' }).click();
  await expect(course.getByRole('alert')).toContainText('请允许麦克风');
  await expect(course.getByRole('button', { name: '录下我的跟读' })).toBeEnabled();
  expect(recognitionRequests).toEqual([]);
});

test('MATCH-15: narrow and enlarged-text course controls remain usable', async ({
  page,
  appUrl,
}) => {
  await guest(page, appUrl);
  await page.getByRole('button', { name: '课堂学习' }).click();
  await page.addStyleTag({ content: 'html { font-size: 150%; }' });
  for (const width of [390, 768]) {
    await page.setViewportSize({ width, height: 900 });
    const course = page.getByRole('region', { name: '课程拼读跟读' });
    await course.scrollIntoViewIfNeeded();
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    for (const button of await course.getByRole('button').all()) {
      const bounds = await button.boundingBox();
      expect(bounds?.height).toBeGreaterThanOrEqual(44);
      expect(bounds?.width).toBeGreaterThanOrEqual(44);
    }
  }
});

for (const action of ['demonstration', 'activity'] as const) {
  test(`MATCH-15: ${action} interruption releases course microphone without assessing speaker audio`, async ({
    page,
    appUrl,
  }) => {
    await installCapture(page);
    const assessments: string[] = [];
    page.on('request', (request) => {
      if (request.url().endsWith('/assess')) assessments.push(request.url());
    });
    await guest(page, appUrl);
    await page.getByRole('checkbox', { name: '语音引导' }).uncheck();
    if (await page.getByRole('button', { name: '完成', exact: true }).isVisible())
      await page.getByRole('button', { name: '完成', exact: true }).click();
    await page.getByRole('button', { name: '课堂学习' }).click();
    const course = page.getByRole('region', { name: '课程拼读跟读' });
    await course.getByText('录音回放（可选）', { exact: false }).click();
    await course.getByRole('button', { name: '录下我的跟读' }).click();
    await expect(course.getByRole('button', { name: '停止录音' })).toBeVisible();
    if (action === 'demonstration')
      await page.getByRole('button', { name: '播放课程录音', exact: true }).click();
    else await page.getByRole('button', { name: '写一写', exact: true }).click();
    await expect
      .poll(() =>
        page.evaluate(() =>
          (window as unknown as { lastCaptureStream: MediaStream }).lastCaptureStream
            .getTracks()
            .every((track) => track.readyState === 'ended'),
        ),
      )
      .toBe(true);
    await expect(course.getByRole('button', { name: '停止录音' })).toHaveCount(0);
    await expect(page.getByLabel('回放课程跟读')).toHaveCount(0);
    expect(assessments).toEqual([]);
  });
}

test('MATCH-15: interrupted pending microphone permission cannot stop the newer demonstration', async ({
  page,
  appUrl,
}) => {
  await installCapture(page);
  const assessments: string[] = [];
  page.on('request', (request) => {
    if (request.url().endsWith('/assess')) assessments.push(request.url());
  });
  await guest(page, appUrl);
  await page.getByRole('checkbox', { name: '语音引导' }).uncheck();
  if (await page.getByRole('button', { name: '完成', exact: true }).isVisible())
    await page.getByRole('button', { name: '完成', exact: true }).click();
  await page.getByRole('button', { name: '课堂学习' }).click();
  await page.evaluate(() => {
    const capture = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
    navigator.mediaDevices.getUserMedia = async (constraints) => {
      const stream = await capture(constraints);
      return new Promise<MediaStream>((resolve) => {
        (window as unknown as { finishPermission: () => void }).finishPermission = () =>
          resolve(stream);
      });
    };
  });
  const course = page.getByRole('region', { name: '课程拼读跟读' });
  await course.getByText('录音回放（可选）', { exact: false }).click();
  await course.getByRole('button', { name: '录下我的跟读' }).click();
  await expect
    .poll(() =>
      page.evaluate(
        () => typeof (window as unknown as { finishPermission?: () => void }).finishPermission,
      ),
    )
    .toBe('function');
  await page.getByRole('button', { name: '播放课程录音', exact: true }).click();
  await expect(course.getByRole('button', { name: '录下我的跟读' })).toBeEnabled();
  await page.evaluate(() =>
    (window as unknown as { finishPermission: () => void }).finishPermission(),
  );
  await expect
    .poll(() =>
      page.evaluate(() =>
        (window as unknown as { lastCaptureStream: MediaStream }).lastCaptureStream
          .getTracks()
          .every((track) => track.readyState === 'ended'),
      ),
    )
    .toBe(true);
  await expect(page.getByRole('button', { name: '停止播放课程录音', exact: true })).toBeVisible();
  await expect(page.getByLabel('回放课程跟读')).toHaveCount(0);
  expect(assessments).toEqual([]);
});
