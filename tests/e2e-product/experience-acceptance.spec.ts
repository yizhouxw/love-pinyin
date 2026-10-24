import { openSection } from '../support/interaction';
import { expect } from '@playwright/test';
import { test } from '../support/real-server';

test.use({ selectedPinyinSource: true });

test('UX-01/02/04/08: main learning actions remain easy to reach on desktop and narrow screens', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  for (const width of [1280, 390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeInViewport();
    await expect(page.getByRole('button', { name: '课堂学习', exact: true })).toBeInViewport();
    await expect(page.locator('.lesson-navigation')).not.toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({ path: test.info().outputPath(`home-${width}.png`), fullPage: true });
  }
  await page.getByRole('button', { name: '课堂学习', exact: true }).click();
  await page.screenshot({ path: test.info().outputPath('lesson-320.png'), fullPage: true });
  await page.getByRole('button', { name: '写一写', exact: true }).click();
  await expect(page.getByRole('checkbox', { name: '语音引导' })).toHaveCount(1);
  await expect(page.getByRole('button', { name: '▶ 播放笔顺', exact: true })).toBeInViewport();
  await page.screenshot({ path: test.info().outputPath('writing-320.png'), fullPage: true });
  await page.getByRole('button', { name: '练一练', exact: true }).click();
  await expect(page.getByRole('button', { name: '开始本课练习', exact: false })).toBeInViewport();
  await page.getByRole('button', { name: '返回学习路线', exact: false }).click();
  await openSection(page, '查看全部课程');
  await page.locator('[data-lesson-id="lesson-14"]').click();
  await expect(page.locator('#lesson-heading-lesson-14')).toBeFocused();
  expect(await page.evaluate(() => scrollY)).toBeLessThan(5);
  await expect(page.getByRole('button', { name: '写一写', exact: true })).toBeInViewport();
  await page.getByRole('button', { name: '返回学习路线', exact: false }).click();
  await expect(page.locator('[data-lesson-id="lesson-14"]')).toBeFocused();
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.locator('.daily-sections button').first().click();
  await expect(page.getByRole('button', { name: '开始跟读', exact: false })).toBeInViewport();
  await expect(page.locator('.daily-days')).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath('daily-320.png'), fullPage: true });
});

test('UX-06: a required standard sample follows the optional prompt automatically, even when that prompt fails', async ({
  page,
  appUrl,
}) => {
  const events: { type: string; source: string; time: number }[] = [];
  await page.addInitScript(() => {
    Object.defineProperty(window, 'lessonMediaEvents', { value: [] });
    const original = HTMLMediaElement.prototype.play;
    const observed = new WeakSet<HTMLMediaElement>();
    HTMLMediaElement.prototype.play = function () {
      if (!observed.has(this)) {
        observed.add(this);
        for (const type of ['playing', 'ended'])
          this.addEventListener(
            type,
            () => {
              (window as unknown as { lessonMediaEvents: unknown[] }).lessonMediaEvents.push({
                type,
                source: this.getAttribute('src'),
                time: performance.now(),
              });
            },
            true,
          );
      }
      return original.call(this);
    };
  });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭' }).click();
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await page.getByRole('combobox').selectOption('lesson-09');
  await page.getByRole('button', { name: '保存', exact: true }).click();
  await page.getByRole('button', { name: '返回学习', exact: true }).click();
  await page.getByRole('button', { name: '开始今天的练习' }).click();
  await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 25000 });
  events.push(
    ...(await page.evaluate(
      () => (window as unknown as { lessonMediaEvents: typeof events }).lessonMediaEvents,
    )),
  );
  const promptEnd = events.find(
    (event) => event.type === 'ended' && event.source.includes('/voice/prompt-'),
  );
  const sampleStart = events.find(
    (event) => event.type === 'playing' && event.source.includes('/audio/'),
  );
  expect(promptEnd).toBeTruthy();
  expect(sampleStart!.time).toBeGreaterThanOrEqual(promptEnd!.time);
  await page.getByRole('button', { name: '退出练习' }).click();
  await page.route('**/api/v1/voice/prompt-*', (route) => route.abort('failed'));
  await page.getByRole('button', { name: '开始今天的练习' }).click();
  await expect(page.getByRole('button', { name: '↻ 重试声音' })).toBeVisible();
  await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 25000 });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: test.info().outputPath('game-390.png'), fullPage: true });
});
