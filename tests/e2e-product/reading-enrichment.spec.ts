import { expect } from '@playwright/test';
import { test } from '../support/real-server';

test.use({ selectedPinyinSource: true });

async function guest(page: import('@playwright/test').Page, url: string) {
  await page.goto(url);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('checkbox', { name: '语音引导', exact: true }).uncheck();
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
      const source = this.src;
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
  await page.getByLabel('连播间隔（秒）').fill('0.1');
  await page.getByRole('button', { name: '保存间隔' }).click();
  await expect(page.getByText('当前间隔：0.1秒')).toBeVisible();
  await page.reload();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await expect(page.getByLabel('连播间隔（秒）')).toHaveValue('0.1');
});

test('READ-03/04: folded examples speak on opening, and Chinese sentences highlight actual syllables', async ({
  page,
  appUrl,
}) => {
  await guest(page, appUrl);
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: '第 3 份', exact: true }).click();
  await page.getByRole('button', { name: /^读音节并组词/ }).click();
  const reader = page.getByLabel('当前跟读内容');
  await expect(reader.getByText('八个', { exact: true })).toHaveCount(0);
  const voice = page.waitForResponse((r) => r.url().endsWith('/voice/daily-example-ba1') && r.ok());
  await reader.getByRole('button', { name: '展开组词样例', exact: true }).click();
  await voice;
  await expect(reader.getByText('八个', { exact: true })).toBeVisible();
  await expect(reader.getByText('八月', { exact: true })).toBeVisible();
  await reader.getByRole('button', { name: '收起组词样例', exact: true }).click();
  await expect(reader.getByText('八个', { exact: true })).toHaveCount(0);
  await reader.getByRole('button', { name: '展开组词样例', exact: true }).click();
  await reader.getByRole('button', { name: '先跳过', exact: true }).click();
  await expect(reader.getByRole('button', { name: '展开组词样例', exact: true })).toBeVisible();
  await expect(reader.getByText('八个', { exact: true })).toHaveCount(0);
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
