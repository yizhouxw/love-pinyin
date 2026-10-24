import { expect, type Locator } from '@playwright/test';
import { test } from '../support/real-server';
import { clearReadingMedia, observeReadingMedia, playedReading } from '../support/media-log';

test.use({ selectedPinyinSource: true });

async function guest(page: import('@playwright/test').Page, url: string) {
  await page.goto(url);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('checkbox', { name: '语音引导', exact: true }).uncheck();
}

async function parentSound(page: import('@playwright/test').Page) {
  const sound = page.getByText(/^声音与(?:播放|显示)设置$/);
  await expect(sound).toBeVisible();
  const details = sound.locator('..');
  if ((await details.getAttribute('open')) === null) await sound.press('Enter');
  const fine = page.getByText(/^精细调整/);
  await expect(fine).toBeVisible();
  if (!(await page.getByLabel('连播间隔（秒）').isVisible())) await fine.press('Enter');
  await expect(page.getByLabel('连播间隔（秒）')).toBeVisible();
}

async function quickGap(container: Locator) {
  const dialog = container.getByRole('dialog', { name: '跟读间隔' });
  if (!(await dialog.isVisible())) await container.locator('.daily-gap-trigger').click();
  if (!(await dialog.getByLabel('连播间隔（秒）').isVisible()))
    await dialog.getByText(/^精细调整/).click();
  return dialog;
}

async function saveQuickGap(container: Locator, seconds: string) {
  const settings = await quickGap(container);
  await settings.getByLabel('连播间隔（秒）').fill(seconds);
  await settings.getByRole('button', { name: '应用间隔', exact: true }).click();
  await expect(settings).not.toBeVisible();
  await expect(container.locator('.daily-gap-trigger')).toHaveAccessibleName(
    `间隔设置，基础间隔${Number(seconds).toFixed(1)}秒`,
  );
}

test('READ-01: family interval is saved, bounded, restored and retained across other settings', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  const code = (await page.locator('.pair-code').innerText()).match(/[A-Z2-9]{8}/)![0];
  await page.getByLabel('家长配对码').fill(code);
  await page.getByRole('button', { name: '连接家庭' }).click();
  const open = async () => {
    await page.getByRole('button', { name: '家长管理' }).click();
    await page.getByRole('button', { name: '我是家长，继续' }).click();
    await parentSound(page);
  };
  await open();
  const gap = page.getByLabel('连播间隔（秒）');
  await expect(gap).toHaveValue('1');
  await expect(gap).toHaveAttribute('min', '0.1');
  await expect(gap).toHaveAttribute('max', '5');
  await expect(gap).toHaveAttribute('step', '0.1');
  await gap.fill('1.25');
  await expect(page.getByRole('button', { name: '保存间隔' })).toBeDisabled();
  await gap.fill('2.7');
  await page.getByRole('button', { name: '保存间隔' }).click();
  await expect(page.getByText('当前间隔：2.7秒')).toBeVisible();
  await page.getByRole('checkbox', { name: '自动朗读题目', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: '自动朗读题目', exact: true })).not.toBeChecked();
  await expect(page.getByRole('checkbox', { name: '自动朗读题目', exact: true })).toBeEnabled();
  await page.reload();
  await open();
  await expect(gap).toHaveValue('2.7');
  const response = await page.request.get(`${appUrl}/api/v1/profiles/export`);
  expect((await response.json()).profile.settings.playbackGapSeconds).toBe(2.7);
});

test('READ-01: real consecutive audio observes the gap and stopping cancels the queued sound', async ({
  page,
  appUrl,
}) => {
  test.setTimeout(45000);
  await page.addInitScript(() => {
    type AudioEvent = { source: string; type: 'start' | 'end'; time: number };
    const events: AudioEvent[] = [];
    (window as unknown as { readingEvents: AudioEvent[] }).readingEvents = events;
    const play = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () {
      const source = this.getAttribute('data-learning-source') || this.src;
      this.addEventListener(
        'playing',
        () => events.push({ source, type: 'start', time: performance.now() }),
        { once: true },
      );
      this.addEventListener(
        'ended',
        () => events.push({ source, type: 'end', time: performance.now() }),
        { once: true },
      );
      return play.call(this);
    };
  });
  await guest(page, appUrl);
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: '开始第 1 份跟读' }).click();
  const reader = page.getByLabel('当前跟读内容');
  await reader.getByRole('button', { name: '连播本节', exact: false }).click();
  const events = () =>
    page.evaluate(() =>
      (
        window as unknown as { readingEvents: { type: string; source: string; time: number }[] }
      ).readingEvents.filter((e) => e.source.includes('/daily-audio/')),
    );
  await expect.poll(async () => (await events()).filter((e) => e.type === 'start').length).toBe(2);
  const observed = await events();
  expect(
    observed.find((e) => e.type === 'start' && e.source.endsWith('/daily-a2'))!.time -
      observed.find((e) => e.type === 'end' && e.source.endsWith('/daily-a1'))!.time,
  ).toBeGreaterThanOrEqual(950);
  await expect.poll(async () => (await events()).filter((e) => e.type === 'end').length).toBe(2);
  await reader.getByRole('button', { name: '停止示范', exact: false }).click();
  await page.waitForTimeout(1250);
  expect((await events()).filter((e) => e.type === 'start')).toHaveLength(2);
  await expect(reader.locator('.daily-highlight')).toHaveCount(0);
  await page.getByRole('button', { name: '返回小岛', exact: false }).click();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await parentSound(page);
  await page.getByLabel('连播间隔（秒）').fill('0.1');
  await page.getByRole('button', { name: '保存间隔' }).click();
  await expect(page.getByText('当前间隔：0.1秒')).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await parentSound(page);
  await expect(page.getByLabel('连播间隔（秒）')).toHaveValue('0.1');
});

test('READ-05: real word syllables share one compact clip and word waits include length', async ({
  page,
  appUrl,
}) => {
  await observeReadingMedia(page);
  await page.addInitScript(() => {
    const sequences: string[][] = [];
    (window as unknown as { readingSequences: string[][] }).readingSequences = sequences;
    const play = HTMLMediaElement.prototype.play;
    HTMLMediaElement.prototype.play = function () {
      const sources = this.getAttribute('data-learning-sources');
      if (sources)
        this.addEventListener('playing', () => sequences.push(JSON.parse(sources) as string[]), {
          once: true,
          capture: true,
        });
      return play.call(this);
    };
  });
  await guest(page, appUrl);
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await parentSound(page);
  await page.getByLabel('连播间隔（秒）').fill('3');
  await page.getByRole('button', { name: '保存间隔' }).click();
  await expect(page.getByText('当前间隔：3.0秒')).toBeVisible();
  await page.getByRole('button', { name: '返回学习', exact: true }).click();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  if (await page.getByRole('button', { name: '换练习', exact: true }).isVisible())
    await page.getByRole('button', { name: '换练习', exact: true }).click();
  await page.getByRole('button', { name: '第 4 份', exact: true }).click();
  await page.getByRole('button', { name: /^拼读词语/ }).click();
  const reader = page.getByLabel('当前跟读内容');
  await expect(page.getByText(/本份声音已就绪/)).toBeVisible();
  const uncached: string[] = [];
  await page.route('**/api/v1/guest/daily-audio/**', async (route) => {
    uncached.push(route.request().url());
    await route.abort();
  });
  await page.evaluate(() => {
    const target = document.querySelector('.daily-target')!;
    const seen: number[] = [];
    (window as unknown as { combinedHighlights: number[] }).combinedHighlights = seen;
    new MutationObserver(() => {
      [...target.querySelectorAll('span')].forEach((span, index) => {
        if (span.classList.contains('daily-highlight') && !seen.includes(index)) seen.push(index);
      });
    }).observe(target, { subtree: true, attributes: true, attributeFilter: ['class'] });
  });
  const events = () =>
    page.evaluate(() =>
      window.readingMediaEvents.filter((event) => event.source.includes('/daily-audio/')),
    );
  // Both syllables must use one native clip, including single replay at a large base setting.
  await reader.locator('.daily-target').click();
  await expect.poll(async () => (await events()).filter((e) => e.type === 'end').length).toBe(1);
  let observed = await events();
  expect(observed.filter((e) => e.type === 'start')).toHaveLength(1);
  expect(observed[1]!.time - observed[0]!.time).toBeLessThan(2500);
  expect(
    await page.evaluate(
      () => (window as unknown as { combinedHighlights: number[] }).combinedHighlights,
    ),
  ).toEqual([0, 1]);
  expect(
    await page.evaluate(() =>
      (window as unknown as { readingSequences: string[][] }).readingSequences.map((sources) =>
        sources.map((source) => source.split('/').at(-1)),
      ),
    ),
  ).toEqual([['daily-da4', 'daily-di4']]);
  await page.evaluate(() => {
    window.readingMediaEvents = [];
    (window as unknown as { readingSequences: string[][] }).readingSequences.length = 0;
  });
  await reader.getByRole('button', { name: '连播本节', exact: false }).click();
  await expect
    .poll(async () => (await events()).filter((e) => e.type === 'end').length, { timeout: 15000 })
    .toBe(2);
  observed = await events();
  expect(observed.filter((e) => e.type === 'start').map((e) => e.source.split('/').at(-1))).toEqual(
    ['daily-da4', 'daily-di4'],
  );
  expect(
    await page.evaluate(() =>
      (window as unknown as { readingSequences: string[][] }).readingSequences.map((sources) =>
        sources.map((source) => source.split('/').at(-1)),
      ),
    ),
  ).toEqual([
    ['daily-da4', 'daily-di4'],
    ['daily-di4', 'daily-tu2'],
  ]);
  const wordWait = observed[2]!.time - observed[1]!.time;
  expect(wordWait).toBeGreaterThanOrEqual(3450);
  expect(wordWait).toBeLessThan(4200);
  await reader.getByRole('button', { name: '停止示范', exact: false }).click();
  await page.waitForTimeout(3750);
  expect((await events()).filter((e) => e.type === 'start')).toHaveLength(2);
  await expect(reader.locator('.daily-highlight')).toHaveCount(0);
  expect(uncached).toEqual([]);
});

test('READ-05: short and long real Chinese sentences wait for their spoken syllable counts', async ({
  page,
  appUrl,
}) => {
  await observeReadingMedia(page);
  await guest(page, appUrl);
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await saveQuickGap(page.getByLabel('天天练拼音', { exact: true }), '0.1');
  const reader = page.getByLabel('当前跟读内容');
  const sentenceEvents = () =>
    page.evaluate(() =>
      window.readingMediaEvents.filter(
        (event) =>
          event.source.includes('/daily-audio/') || event.source.includes('/voice/daily-word-'),
      ),
    );
  const sentenceWait = async (firstNarration: string, expectedMilliseconds: number) => {
    await clearReadingMedia(page);
    await reader.getByRole('button', { name: '连播本节', exact: false }).click();
    await expect
      .poll(async () => (await sentenceEvents()).filter((event) => event.type === 'start').length, {
        timeout: 20000,
      })
      .toBe(2);
    const events = await sentenceEvents();
    expect(events[0]!.source).toContain(`/voice/${firstNarration}`);
    const wait = events[2]!.time - events[1]!.time;
    expect(wait).toBeGreaterThanOrEqual(expectedMilliseconds - 50);
    expect(wait).toBeLessThan(expectedMilliseconds + 700);
    await reader.getByRole('button', { name: '停止示范', exact: false }).click();
    await expect(reader.locator('.daily-highlight')).toHaveCount(0);
  };

  if (await page.getByRole('button', { name: '换练习', exact: true }).isVisible())
    await page.getByRole('button', { name: '换练习', exact: true }).click();
  await page.getByRole('button', { name: '第 5 份', exact: true }).click();
  await page.getByRole('button', { name: /^拼读句子/ }).click();
  await expect(page.getByText(/本份声音已就绪/)).toBeVisible();
  // dì di kū le: four displayed syllables, despite only three standard-audio IDs.
  await sentenceWait('daily-word-day-05-s5-i1', 1600);
  if (await page.getByRole('button', { name: '换练习', exact: true }).isVisible())
    await page.getByRole('button', { name: '换练习', exact: true }).click();
  await page.getByRole('button', { name: '第 10 份', exact: true }).click();
  await page.getByRole('button', { name: /^读句子/ }).click();
  await expect(page.getByText(/本份声音已就绪/)).toBeVisible();
  await page.getByLabel('第10份本节内容').getByRole('button').nth(2).click();
  await reader.getByRole('button', { name: '停止示范', exact: false }).click();
  // dì di bēi zhe yí gè dà shuǐ hú: nine syllables, seven standard-audio IDs.
  await sentenceWait('daily-word-day-10-s6-i3', 4100);
});

test('READ-06: guest quick settings work by keyboard on narrow screens and cancel queued audio', async ({
  page,
  appUrl,
}) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await observeReadingMedia(page);
  await guest(page, appUrl);
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  const daily = page.getByLabel('天天练拼音', { exact: true });
  await daily.locator('.daily-gap-trigger').focus();
  await page.keyboard.press('Enter');
  let settings = daily.getByRole('dialog', { name: '跟读间隔' });
  await settings.getByText(/^精细调整/).click();
  const input = settings.getByLabel('连播间隔（秒）');
  await expect(input).toHaveValue('1');
  await expect(input).toHaveAttribute('min', '0.1');
  await expect(input).toHaveAttribute('max', '5');
  await expect(input).toHaveAttribute('step', '0.1');
  await input.fill('1.25');
  await expect(settings.getByRole('alert')).toContainText('最多一位小数');
  await expect(settings.getByRole('button', { name: '应用间隔' })).toBeDisabled();
  await input.fill('2.5');
  await settings.getByRole('button', { name: '应用间隔' }).focus();
  await page.keyboard.press('Enter');
  await expect(settings).not.toBeVisible();
  await expect(daily.locator('.daily-gap-trigger')).toHaveAccessibleName('间隔设置，基础间隔2.5秒');
  await page.getByRole('button', { name: '开始第 1 份跟读' }).click();
  const reader = page.getByLabel('当前跟读内容');
  settings = await quickGap(reader);
  await expect(settings.getByLabel('连播间隔（秒）')).toHaveValue('2.5');
  await expect(settings).toContainText('这条读完后，留2.5秒跟读');
  await settings.getByRole('button', { name: '关闭间隔设置' }).click();
  await clearReadingMedia(page);
  await reader.getByRole('button', { name: '连播本节', exact: false }).click();
  await expect
    .poll(async () =>
      page.evaluate(
        () =>
          window.readingMediaEvents.filter(
            (event) => event.type === 'end' && event.source.includes('/daily-audio/'),
          ).length,
      ),
    )
    .toBe(1);
  await saveQuickGap(reader, '0.2');
  await page.waitForTimeout(2800);
  expect(await playedReading(page, 'daily-audio')).toHaveLength(1);
  await expect(reader.locator('.daily-highlight')).toHaveCount(0);
  settings = await quickGap(reader);
  await expect(settings).toContainText('这条读完后，留0.2秒跟读');
  await settings.getByRole('button', { name: '关闭间隔设置' }).click();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  if (await page.getByRole('button', { name: '换练习', exact: true }).isVisible())
    await page.getByRole('button', { name: '换练习', exact: true }).click();
  await page.getByRole('button', { name: '第 4 份', exact: true }).click();
  await expect(daily.locator('.daily-gap-trigger')).toHaveAccessibleName('间隔设置，基础间隔0.2秒');
  await page.getByRole('button', { name: /^拼读词语/ }).click();
  settings = await quickGap(reader);
  await expect(settings.getByLabel('连播间隔（秒）')).toHaveValue('0.2');
  await expect(settings).toContainText('这条读完后，留0.7秒跟读');
  await settings.getByLabel('连播间隔（秒）').fill('0.3');
  await expect(settings.getByRole('button', { name: '应用间隔' })).toBeEnabled();
  await settings.getByRole('button', { name: '取消', exact: true }).click();
  // Hold the browser permission response to cover the recording-preparation boundary.
  await page.evaluate(() => {
    Object.defineProperty(navigator, 'mediaDevices', {
      configurable: true,
      value: {
        getUserMedia: () =>
          new Promise<MediaStream>((_resolve, reject) => {
            (window as unknown as { denyReadingMicrophone: () => void }).denyReadingMicrophone =
              () => reject(new DOMException('denied', 'NotAllowedError'));
          }),
      },
    });
  });
  if (
    !(await reader.getByRole('button', { name: '录下我的跟读', exact: false }).isVisible()) &&
    !(await reader.getByRole('button', { name: '重新录音', exact: false }).isVisible())
  )
    await reader.getByText('录音比较（可选）', { exact: true }).click();
  await reader.getByRole('button', { name: '录下我的跟读' }).click();
  await expect(reader.getByRole('status')).toContainText('正在准备录音');
  settings = await quickGap(reader);
  await expect(settings.getByLabel('连播间隔（秒）')).toBeDisabled();
  await expect(settings.getByLabel('调节基础间隔')).toBeDisabled();
  await expect(settings.getByRole('button', { name: '紧凑 0.5秒', exact: true })).toBeDisabled();
  await expect(settings.getByRole('button', { name: '应用间隔' })).toBeDisabled();
  await page.evaluate(() => {
    (window as unknown as { denyReadingMicrophone: () => void }).denyReadingMicrophone();
  });
  await expect(settings.getByLabel('连播间隔（秒）')).toBeEnabled();
  await settings.getByRole('button', { name: '关闭间隔设置' }).click();
  await expect(reader.getByRole('alert')).toContainText('麦克风没有开启');
  await page.reload();
  await expect(daily.locator('.daily-gap-trigger')).toHaveAccessibleName('间隔设置，基础间隔0.2秒');
  expect(
    await page.evaluate(() => ({
      guest: JSON.parse(sessionStorage.getItem('lp.guest.playback-gap')!),
      family: localStorage.getItem('love-pinyin.playback-gap'),
    })),
  ).toEqual({ guest: { seconds: 0.2, familyDefault: 1 }, family: null });
  await page
    .getByLabel('访客模式', { exact: true })
    .getByRole('button', { name: '清除并退出访客' })
    .click();
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await expect(daily.locator('.daily-gap-trigger')).toHaveAccessibleName('间隔设置，基础间隔1.0秒');
  expect(await page.evaluate(() => sessionStorage.getItem('lp.guest.playback-gap'))).toBeNull();
});

test('READ-06: a real learning device remembers its own gap without parent writes and follows new defaults', async ({
  page,
  appUrl,
  browser,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭' }).click();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await parentSound(page);
  await page.getByLabel('连播间隔（秒）').fill('2');
  await page.getByRole('button', { name: '保存间隔' }).click();
  await expect(page.getByText('当前间隔：2.0秒')).toBeVisible();
  await page
    .locator('summary')
    .filter({ hasText: /^连接其他设备$/ })
    .click();
  await page.getByRole('button', { name: '生成配对码', exact: true }).click();
  const code = await page
    .getByRole('region', { name: '配对码管理' })
    .getByLabel('新生成的配对码')
    .inputValue();
  const learningContext = await browser.newContext();
  try {
    const learning = await learningContext.newPage();
    const settingWrites: string[] = [];
    learning.on('request', (request) => {
      if (request.method() === 'PUT' && request.url().endsWith('/household/settings'))
        settingWrites.push(request.url());
    });
    await learning.goto(appUrl.replace('127.0.0.1', 'localhost'));
    await learning.getByLabel('家长配对码', { exact: true }).fill(code);
    await learning.getByRole('button', { name: '连接家庭' }).click();
    await expect(learning.getByLabel('家庭模式', { exact: true })).toContainText(
      '进度已连接家庭 Mac',
    );
    expect(
      (await (await learning.request.get(new URL('/api/v1/bootstrap', learning.url()).href)).json())
        .device.isParent,
    ).toBe(false);
    await expect(learning.getByRole('button', { name: '家长管理' })).toHaveCount(0);
    await learning.getByRole('button', { name: '进入天天练拼音' }).click();
    const daily = learning.getByLabel('天天练拼音', { exact: true });
    await expect(daily.locator('.daily-gap-trigger')).toHaveAccessibleName(
      '间隔设置，基础间隔2.0秒',
    );
    await saveQuickGap(daily, '0.4');
    await learning.getByRole('button', { name: '开始第 1 份跟读' }).click();
    await expect(
      learning.getByLabel('当前跟读内容').locator('.daily-gap-trigger'),
    ).toHaveAccessibleName('间隔设置，基础间隔0.4秒');
    if (await learning.getByRole('button', { name: '换练习', exact: true }).isVisible())
      await learning.getByRole('button', { name: '换练习', exact: true }).click();
    await learning.getByRole('button', { name: '第 4 份', exact: true }).click();
    await expect(daily.locator('.daily-gap-trigger')).toHaveAccessibleName(
      '间隔设置，基础间隔0.4秒',
    );
    await learning.getByRole('button', { name: /^拼读词语/ }).click();
    await expect(
      learning.getByLabel('当前跟读内容').locator('.daily-gap-trigger'),
    ).toHaveAccessibleName('间隔设置，基础间隔0.4秒');
    await learning.getByRole('button', { name: '返回小岛', exact: false }).click();
    await learning.reload();
    await learning.getByRole('button', { name: '进入天天练拼音' }).click();
    await expect(daily.locator('.daily-gap-trigger')).toHaveAccessibleName(
      '间隔设置，基础间隔0.4秒',
    );
    expect(
      await learning.evaluate(() => JSON.parse(localStorage.getItem('love-pinyin.playback-gap')!)),
    ).toEqual({ seconds: 0.4, familyDefault: 2 });
    expect(settingWrites).toEqual([]);
    const backup = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
    expect(backup.profile.settings.playbackGapSeconds).toBe(2);

    await parentSound(page);
    await page.getByLabel('连播间隔（秒）').fill('3.1');
    await page.getByRole('button', { name: '保存间隔' }).click();
    await expect(page.getByText('当前间隔：3.1秒')).toBeVisible();
    await learning.reload();
    await expect(daily.locator('.daily-gap-trigger')).toHaveAccessibleName(
      '间隔设置，基础间隔3.1秒',
    );
    await expect((await quickGap(daily)).getByLabel('连播间隔（秒）')).toHaveValue('3.1');
    expect(settingWrites).toEqual([]);
  } finally {
    await learningContext.close();
  }
});

test('READ-07: compact controls preview drafts, dismiss safely and fit narrow viewports', async ({
  page,
  appUrl,
}) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await guest(page, appUrl);
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  const daily = page.getByLabel('天天练拼音', { exact: true });
  const trigger = daily.locator('.daily-gap-trigger');
  await expect(trigger).toHaveAccessibleName('间隔设置，基础间隔1.0秒');
  await expect(trigger).toHaveAttribute('aria-haspopup', 'dialog');
  const triggerBounds = await trigger.boundingBox();
  expect(triggerBounds!.width).toBeLessThan(240);
  expect(triggerBounds!.height).toBeGreaterThanOrEqual(44);
  await daily.screenshot({ path: test.info().outputPath('gap-settings-desktop-entry.png') });
  const originalOverflow = await page.evaluate(() => ({
    body: document.body.style.overflow,
    root: document.documentElement.style.overflow,
  }));
  let settings = await quickGap(daily);
  await expect(settings).toBeVisible();
  await expect(settings).toContainText('词句越长，留给你跟读的时间越多。');
  expect(
    await page.evaluate(() => ({
      body: document.body.style.overflow,
      root: document.documentElement.style.overflow,
    })),
  ).toEqual({ body: 'hidden', root: 'hidden' });
  await trigger.focus();
  expect(await settings.evaluate((dialog) => dialog.contains(document.activeElement))).toBe(true);
  for (let step = 0; step < 12; step += 1) {
    await page.keyboard.press('Tab');
    // Native modals may yield to browser chrome, but no background page control may receive focus.
    expect(
      await settings.evaluate(
        (dialog) =>
          document.activeElement === document.body || dialog.contains(document.activeElement),
      ),
    ).toBe(true);
  }
  const input = settings.getByLabel('连播间隔（秒）');
  const range = settings.getByLabel('调节基础间隔');
  await settings.getByRole('button', { name: '紧凑 0.5秒', exact: true }).click();
  await expect(input).toHaveValue('0.5');
  await expect(settings.getByRole('button', { name: '紧凑 0.5秒', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await settings.getByRole('button', { name: '增加0.1秒', exact: true }).click();
  await expect(input).toHaveValue('0.6');
  await settings.getByRole('button', { name: '减少0.1秒', exact: true }).click();
  await expect(input).toHaveValue('0.5');
  await range.focus();
  await page.keyboard.press('ArrowRight');
  await expect(input).toHaveValue('0.6');
  await page.keyboard.press('Home');
  await expect(input).toHaveValue('0.1');
  await expect(settings.getByRole('button', { name: '减少0.1秒', exact: true })).toBeDisabled();
  await page.keyboard.press('End');
  await expect(input).toHaveValue('5');
  await expect(settings.getByRole('button', { name: '增加0.1秒', exact: true })).toBeDisabled();
  await page.keyboard.press('ArrowLeft');
  await expect(input).toHaveValue('4.9');
  await input.fill('0');
  await expect(input).toHaveAttribute('aria-invalid', 'true');
  await expect(input).toHaveAccessibleDescription('请输入0.1～5秒，最多一位小数。');
  await expect(settings.getByRole('alert')).toContainText('0.1～5秒');
  await expect(settings.getByRole('button', { name: '应用间隔' })).toBeDisabled();
  await input.fill('5.1');
  await expect(settings.getByRole('button', { name: '应用间隔' })).toBeDisabled();
  await input.fill('2.4');
  await expect(input).toHaveAttribute('aria-invalid', 'false');
  await settings.getByRole('button', { name: '应用间隔' }).click();
  await expect(settings).not.toBeVisible();
  await expect(trigger).toBeFocused();
  await expect(trigger).toHaveAccessibleName('间隔设置，基础间隔2.4秒');
  expect(
    await page.evaluate(() => ({
      body: document.body.style.overflow,
      root: document.documentElement.style.overflow,
    })),
  ).toEqual(originalOverflow);
  for (const dismissal of ['取消', '关闭间隔设置', 'Escape', 'backdrop']) {
    settings = await quickGap(daily);
    await expect(settings.getByLabel('连播间隔（秒）')).toHaveValue('2.4');
    await settings.getByRole('button', { name: '从容 2.0秒', exact: true }).click();
    if (dismissal === 'Escape') await page.keyboard.press('Escape');
    else if (dismissal === 'backdrop') await page.mouse.click(8, 8);
    else await settings.getByRole('button', { name: dismissal, exact: true }).click();
    await expect(settings).not.toBeVisible();
    await expect(trigger).toBeFocused();
    await expect(trigger).toHaveAccessibleName('间隔设置，基础间隔2.4秒');
  }
  if (await page.getByRole('button', { name: '换练习', exact: true }).isVisible())
    await page.getByRole('button', { name: '换练习', exact: true }).click();
  await page.getByRole('button', { name: '第 4 份', exact: true }).click();
  await page.getByRole('button', { name: /^拼读词语/ }).click();
  const reader = page.getByLabel('当前跟读内容');
  settings = await quickGap(reader);
  await expect(settings).toContainText('这条读完后，留2.9秒跟读');
  await settings.getByRole('button', { name: '紧凑 0.5秒', exact: true }).click();
  await expect(settings).toContainText('这条读完后，留1.0秒跟读');
  await settings.getByRole('button', { name: '增加0.1秒', exact: true }).click();
  await expect(settings).toContainText('这条读完后，留1.1秒跟读');
  await settings.getByRole('button', { name: '适中 1.0秒', exact: true }).click();
  await expect(settings).toContainText('这条读完后，留1.5秒跟读');
  await page.screenshot({ path: test.info().outputPath('gap-settings-desktop-dialog.png') });
  await settings.getByRole('button', { name: '应用间隔' }).click();
  await expect(settings).not.toBeVisible();
  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    settings = await quickGap(reader);
    const bounds = await settings.boundingBox();
    expect(bounds!.x).toBeGreaterThanOrEqual(0);
    expect(bounds!.y).toBeGreaterThanOrEqual(0);
    expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(width);
    expect(bounds!.y + bounds!.height).toBeLessThanOrEqual(844);
    expect(
      await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth),
    ).toBe(true);
    await expect(settings.getByRole('button', { name: '应用间隔' })).toBeInViewport();
    if (width === 390)
      await page.screenshot({ path: test.info().outputPath('gap-settings-390-dialog.png') });
    await settings.getByRole('button', { name: '关闭间隔设置' }).click();
    await expect(reader.locator('.daily-gap-trigger')).toBeFocused();
  }
});

test('READ-03/04: folded examples speak on opening, and Chinese sentences highlight actual syllables', async ({
  page,
  appUrl,
}) => {
  await observeReadingMedia(page);
  await guest(page, appUrl);
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  if (await page.getByRole('button', { name: '换练习', exact: true }).isVisible())
    await page.getByRole('button', { name: '换练习', exact: true }).click();
  await page.getByRole('button', { name: '第 3 份', exact: true }).click();
  await page.getByRole('button', { name: /^读音节并组词/ }).click();
  const reader = page.getByLabel('当前跟读内容');
  await expect(reader.getByText('八个', { exact: true })).toHaveCount(0);
  await reader.getByRole('button', { name: '展开组词样例', exact: true }).click();
  await expect
    .poll(async () => (await playedReading(page, 'voice')).includes('daily-example-ba1'))
    .toBe(true);
  await expect(reader.getByText('八个', { exact: true })).toBeVisible();
  await expect(reader.getByText('八月', { exact: true })).toBeVisible();
  await reader.getByRole('button', { name: '收起组词样例', exact: true }).click();
  await expect(reader.getByText('八个', { exact: true })).toHaveCount(0);
  await reader.getByRole('button', { name: '展开组词样例', exact: true }).click();
  await reader.getByRole('button', { name: '先跳过', exact: true }).click();
  await expect(reader.getByRole('button', { name: '展开组词样例', exact: true })).toBeVisible();
  await expect(reader.getByText('八个', { exact: true })).toHaveCount(0);
  if (await page.getByRole('button', { name: '换练习', exact: true }).isVisible())
    await page.getByRole('button', { name: '换练习', exact: true }).click();
  await page.getByRole('button', { name: '第 5 份', exact: true }).click();
  await page.getByRole('button', { name: /^拼读句子/ }).click();
  await page.evaluate(() => {
    const target = document.querySelector('.daily-target')!;
    const seen: number[] = [];
    (window as unknown as { readingHighlights: number[] }).readingHighlights = seen;
    new MutationObserver(() => {
      [...target.querySelectorAll('span')].forEach((span, i) => {
        if (span.classList.contains('daily-highlight') && !seen.includes(i)) seen.push(i);
      });
    }).observe(target, { subtree: true, attributes: true, attributeFilter: ['class'] });
  });
  await reader.locator('.daily-target').click();
  await expect
    .poll(() =>
      page.evaluate(
        () => (window as unknown as { readingHighlights: number[] }).readingHighlights.length,
      ),
    )
    .toBe(4);
  await expect(reader.getByRole('status')).toContainText('轮到你读啦');
  await expect(reader.locator('.daily-highlight')).toHaveCount(0);
  await reader.locator('.daily-target').click();
  await expect(reader.locator('.daily-highlight')).toHaveCount(1);
  await reader.getByRole('button', { name: '停止示范', exact: false }).click();
  await expect(reader.locator('.daily-highlight')).toHaveCount(0);
});
