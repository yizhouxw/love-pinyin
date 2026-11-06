import { expect } from '@playwright/test';
import { test } from '../support/real-server';

test('WORD-01/02/03: real voices, hidden dictation, text highlights and device practice', async ({
  page,
  appUrl,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在本机生成家长配对码' }).click();
  const code = (await page.locator('.pair-code').innerText()).match(/[A-Z2-9]{8}/)![0];
  await page.getByLabel('家长配对码').fill(code);
  await page.getByRole('button', { name: '连接家庭' }).click();
  await page.getByRole('button', { name: '进入词语天天练 →' }).click();
  await expect(page.getByRole('heading', { name: '词语天天练', exact: true })).toBeVisible();
  const voice = page.waitForResponse(
    (response) => response.url().includes('/voice/word-say-') && response.ok(),
  );
  await page.getByRole('button', { name: '听读天上', exact: true }).click();
  expect((await voice).headers()['content-type']).toContain('audio/');
  const decoded = await page.evaluate(async () => {
    const response = await fetch(
      document.querySelector('audio')?.src || '/api/v1/voice/word-ui-read',
    );
    const context = new AudioContext();
    try {
      const buffer = await context.decodeAudioData(await response.arrayBuffer());
      return buffer.duration;
    } finally {
      await context.close();
    }
  });
  expect(decoded).toBeGreaterThan(0.1);
  await page.getByLabel('选择课程').selectOption({ label: '2. 金木水火土' });
  await expect(page.locator('.word-playback')).toBeEmpty();
  await page.getByRole('button', { name: '词语听写', exact: true }).click();
  await expect(page.locator('.word-answer')).toHaveText('听一听，在纸上写一写');
  await page.getByRole('button', { name: '听词语 / 重听' }).click();
  await page.getByRole('button', { name: '揭晓答案', exact: true }).click();
  await expect(page.locator('.word-answer')).toContainText('一');
  await page.getByRole('button', { name: '下一个', exact: true }).click();
  await expect(page.locator('.word-answer')).toHaveText('听一听，在纸上写一写');
  await page.getByRole('button', { name: '课文背诵', exact: true }).click();
  await expect(page.locator('.word-passage')).toContainText('天地分上下');
  await expect(page.locator('.word-mark-character').first()).toBeVisible();
  await page.getByRole('button', { name: '隐藏正文，试着背' }).click();
  await expect(page.locator('.word-passage')).not.toContainText('天地分上下');
  await page.getByRole('button', { name: '显示正文', exact: true }).click();
  await page.getByRole('button', { name: '这部分我练习过了', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('已记录');
  await page.reload();
  await page.getByLabel('选择课程').selectOption({ label: '2. 金木水火土' });
  await expect(page.getByRole('button', { name: '课文背诵 ✓', exact: true })).toBeVisible();
  await page.setViewportSize({ width: 375, height: 812 });
  await page.getByRole('button', { name: '课文背诵 ✓', exact: true }).click();
  await page.screenshot({ path: test.info().outputPath('word-recite-mobile.png'), fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  expect(errors).toEqual([]);
});

test('WORD-03: guest leaves no persistent marks', async ({ page, appUrl }) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '进入词语天天练 →' }).click();
  await page.getByRole('button', { name: '这部分我练习过了', exact: true }).click();
  expect(
    await page.evaluate(() => localStorage.getItem('love-pinyin-word-practice-v1')),
  ).toBeNull();
  await page.getByRole('button', { name: '清除并退出访客', exact: true }).click();
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await expect(page.getByRole('heading', { name: '词语天天练', exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '这部分我练习过了', exact: true })).toBeEnabled();
});

test('WORD-03: blocked storage is retryable without claiming saved marks', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在本机生成家长配对码' }).click();
  const code = (await page.locator('.pair-code').innerText()).match(/[A-Z2-9]{8}/)![0];
  await page.getByLabel('家长配对码').fill(code);
  await page.getByRole('button', { name: '连接家庭' }).click();
  await page.getByRole('button', { name: '进入词语天天练 →' }).click();
  await page.evaluate(() => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key === 'love-pinyin-word-practice-v1')
        throw new DOMException('Blocked', 'QuotaExceededError');
      original.call(this, key, value);
    };
  });
  await page.getByRole('button', { name: '这部分我练习过了', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('未保存');
  await expect(page.getByRole('button', { name: '这部分我练习过了', exact: true })).toBeEnabled();
  await page.getByRole('button', { name: '词语听写', exact: true }).click();
  await expect(
    page.getByText('这课材料没有听写任务，可以去练习词语拼读。', { exact: true }),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: '这部分我练习过了', exact: true })).toHaveCount(0);
});
