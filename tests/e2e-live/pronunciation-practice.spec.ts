import { expect } from '@playwright/test';
import { test } from '../support/real-server';

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

test('MATCH-13/15: course capture reaches the real unavailable backend and clears on target change', async ({
  page,
  appUrl,
}) => {
  await installCapture(page);
  await guest(page, appUrl);
  await page.getByRole('checkbox', { name: '语音引导' }).uncheck();
  await page.getByRole('button', { name: '课堂学习' }).click();
  const course = page.getByRole('region', { name: '课程拼读跟读' });
  await expect(course).toBeVisible();
  await course.getByRole('button', { name: '录下我的跟读' }).click();
  const stop = course.getByRole('button', { name: '停止录音并识别' });
  await expect(stop).toBeVisible();
  await page.waitForTimeout(1000);
  const response = page.waitForResponse((value) =>
    value.url().includes('/pronunciation/rt-01-a1/assess'),
  );
  await stop.click();
  const body = await (await response).json();
  expect(body.match.status).toBe('unavailable');
  expect(body.saved).toBe(false);
  const result = course.getByRole('region', { name: '拼读准确情况' });
  await expect(result).toContainText('拼读识别暂不可用，不算读错');
  await expect(page.getByLabel('回放课程跟读')).toBeVisible();
  await result.getByText('查看本条拼读记录').click();
  await expect(result).toContainText('有效判断 0 次');
  await page.screenshot({
    path: `test-results/pronunciation-${test.info().project.name}.png`,
    fullPage: true,
  });
  let release!: () => void;
  const gate = new Promise<void>((resolve) => {
    release = resolve;
  });
  let requested = false;
  await page.route('**/pronunciation/rt-01-a1/assess', async (route) => {
    const response = await route.fetch();
    requested = true;
    await gate;
    await route.fulfill({ response }).catch(() => undefined);
  });
  await course.getByRole('button', { name: '重新录音' }).click();
  await expect(stop).toBeVisible();
  await page.waitForTimeout(1000);
  await stop.click();
  await expect.poll(() => requested).toBe(true);
  await course
    .getByRole('navigation', { name: '选择跟读目标' })
    .getByRole('button', { name: 'é', exact: true })
    .click();
  release();
  await expect(page.getByLabel('回放课程跟读')).toHaveCount(0);
  await expect(result).not.toContainText('本次没有保存真实识别成绩');
  await page.getByRole('button', { name: '返回学习路线' }).click();
  await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeEnabled();
});

test('MATCH-13/15: daily capture shares the port, supports cancellation and keeps existing ASR separate', async ({
  page,
  appUrl,
}) => {
  await installCapture(page);
  await guest(page, appUrl);
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: '开始第 1 份跟读' }).click();
  await page.getByRole('checkbox', { name: '语音引导' }).uncheck();
  await page.getByText('录音比较（可选）', { exact: true }).click();
  await page.getByRole('button', { name: '录下我的跟读' }).click();
  const stop = page.getByRole('button', { name: '停止录音', exact: false });
  await expect(stop).toBeVisible();
  await page.waitForTimeout(1000);
  const response = page.waitForResponse((value) =>
    value.url().includes('/pronunciation/day-01-s1-i1/assess'),
  );
  await stop.click();
  const assessed = await response;
  const assessmentBody = await assessed.json();
  expect(assessed.ok(), JSON.stringify(assessmentBody)).toBe(true);
  expect(assessmentBody.match.status).toBe('unavailable');
  const result = page.getByRole('region', { name: '拼读准确情况' });
  await expect(result).toContainText('不算读错');
  await expect(page.getByRole('button', { name: '读过了，下一条' })).toBeEnabled();
  await page.getByRole('button', { name: '清除这段录音' }).click();
  await expect(result).toHaveCount(0);
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
  await page.getByRole('button', { name: '课堂学习' }).click();
  const course = page.getByRole('region', { name: '课程拼读跟读' });
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
