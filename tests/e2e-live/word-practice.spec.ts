import { expect, type Page } from '@playwright/test';

async function chooseLesson(page: Page, title: string) {
  await page.getByRole('button', { name: /^选择课程/ }).click();
  await page
    .getByRole('dialog')
    .getByRole('button', { name: `选择${title}`, exact: true })
    .click();
}
import { test } from '../support/real-server';
import wordImages from '../../content/word-practice/images.json' with { type: 'json' };

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
  await expect(
    page.getByRole('figure', { name: '词语图片：天上', exact: true }).getByRole('img'),
  ).toBeVisible();
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
  await chooseLesson(page, '金木水火土');
  await expect(page.locator('.word-playback')).not.toContainText('正在播放');
  await page.getByRole('button', { name: '词语听写', exact: true }).click();
  await expect(page.locator('.word-answer')).toHaveText('听一听，在纸上写一写');
  await expect(page.locator('.word-dictation img')).toBeHidden();
  await page.getByRole('button', { name: '听词语 / 重听' }).click();
  await page.getByRole('button', { name: '揭晓答案', exact: true }).click();
  await expect(page.locator('.word-answer')).toContainText('一');
  await page.getByRole('button', { name: '下一个', exact: true }).click();
  await expect(page.locator('.word-answer')).toHaveText('听一听，在纸上写一写');
  await page.getByRole('button', { name: '课文背诵', exact: true }).click();
  await expect(page.locator('.word-passage')).toContainText('天地分上下');
  await expect(page.locator('.word-mark-character').first()).toBeVisible();
  await page.getByRole('button', { name: '隐藏正文，试着背' }).click();
  await expect(page.locator('.word-hidden-text').first()).toBeHidden();
  await page.getByRole('button', { name: '显示正文', exact: true }).click();
  await page.getByRole('button', { name: '这部分我练习过了', exact: true }).click();
  await expect(page.getByRole('status')).toContainText('已记录');
  await page.reload();
  await chooseLesson(page, '金木水火土');
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

test('WORD-04/05/06: shared guidance, finite continuous words and stable playing/error layout', async ({
  page,
  appUrl,
}) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '进入词语天天练 →' }).click();
  const guidance = page.getByRole('checkbox', { name: '语音引导', exact: true });
  await guidance.setChecked(false);
  let instructions = 0;
  page.on('request', (request) => {
    if (request.url().includes('/voice/word-ui-')) instructions++;
  });
  await page.getByRole('button', { name: '词语听写', exact: true }).click();
  await page.getByRole('button', { name: '词语拼读', exact: true }).click();
  expect(instructions).toBe(0);
  await guidance.setChecked(true);
  const automatic = page.waitForResponse(
    (response) => response.url().includes('/voice/word-ui-write') && response.ok(),
  );
  await page.getByRole('button', { name: '词语听写', exact: true }).click();
  await automatic;
  await guidance.setChecked(false);
  await expect(page.locator('.word-playback')).not.toContainText('正在播放');
  await page.getByRole('button', { name: '词语拼读', exact: true }).click();
  await page.getByRole('button', { name: '返回首页' }).click();
  await expect(page.getByRole('checkbox', { name: '语音引导', exact: true })).not.toBeChecked();
  await page.getByRole('button', { name: '进入词语天天练 →' }).click();
  await page.setViewportSize({ width: 375, height: 812 });
  const gridY = () =>
    page.locator('.word-grid').evaluate((node) => node.getBoundingClientRect().top + scrollY);
  const initial = await gridY();
  await page.getByRole('button', { name: '连读本课', exact: true }).click();
  await expect(page.locator('.word-grid [aria-current="true"]')).toHaveCount(1);
  await expect(page.locator('.word-playback')).toContainText('连读 1 / 10');
  await expect(page.locator('.word-playback')).toContainText('连读 2 / 10', { timeout: 15000 });
  expect(Math.abs((await gridY()) - initial)).toBeLessThan(1);
  await page.getByRole('button', { name: '停止播放', exact: true }).click();
  await expect(page.locator('.word-playback')).not.toContainText('正在播放');
  expect(Math.abs((await gridY()) - initial)).toBeLessThan(1);
  await page.route('**/guest/voice/word-say-*', (route) => route.abort());
  await page.getByRole('button', { name: '听读天上', exact: true }).click();
  await expect(page.getByRole('alert')).toContainText('声音暂时不可用');
  expect(Math.abs((await gridY()) - initial)).toBeLessThan(1);
  for (const width of [1280, 375]) {
    await page.setViewportSize({ width, height: 900 });
    await page.evaluate(() => {
      document.documentElement.style.fontSize = '200%';
    });
    await page.getByRole('button', { name: '停止播放', exact: true }).click();
    const enlarged = await gridY();
    await page.getByRole('button', { name: '听读天上', exact: true }).click();
    await expect(page.getByRole('alert')).toContainText('声音暂时不可用');
    expect(Math.abs((await gridY()) - enlarged)).toBeLessThan(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.evaluate(() => {
      document.documentElement.style.fontSize = '';
    });
  }
  await page.getByRole('button', { name: '下一课', exact: true }).click();
  await page.getByRole('button', { name: '词语听写', exact: true }).click();
  const bounds = await page.locator('.word-dictation').boundingBox();
  await page.getByRole('button', { name: '揭晓答案', exact: true }).click();
  const revealed = await page.locator('.word-dictation').boundingBox();
  expect(revealed?.height).toBe(bounds?.height);
  await page.evaluate(() => {
    document.documentElement.style.fontSize = '200%';
  });
  const enlargedAnswer = await page.locator('.word-dictation').boundingBox();
  await page.getByRole('button', { name: '收起答案', exact: true }).click();
  expect((await page.locator('.word-dictation').boundingBox())?.height).toBe(
    enlargedAnswer?.height,
  );
  expect(
    await page.locator('.word-answer').evaluate((node) => node.scrollHeight <= node.clientHeight),
  ).toBe(true);
  await page.evaluate(() => {
    document.documentElement.style.fontSize = '';
  });
  await page.getByRole('button', { name: '课文背诵', exact: true }).click();
  const fullHeight = await page
    .locator('.word-passage')
    .evaluate((node) => node.getBoundingClientRect().height);
  await page.getByRole('button', { name: '隐藏正文，试着背' }).click();
  expect(
    await page.locator('.word-passage').evaluate((node) => node.getBoundingClientRect().height),
  ).toBe(fullHeight);
  await page.screenshot({ path: test.info().outputPath('word-stable-mobile.png'), fullPage: true });
});

test('WORD-07/08/09: touch course units, selected pictures and home entry order', async ({
  page,
  appUrl,
}) => {
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await expect(page.locator('.daily-entry h2')).toHaveText([
    '天天练拼音',
    '词语天天练',
    '拼音游戏乐园',
  ]);
  await page.getByRole('button', { name: '进入词语天天练 →' }).click();
  const course = page.getByRole('button', { name: /^选择课程/ });
  expect((await page.locator('.word-header').boundingBox())!.height).toBeLessThanOrEqual(64);
  expect(
    (await page.locator('.word-toolbar .guidance-switch').boundingBox())!.height,
  ).toBeLessThanOrEqual(52);
  await course.click();
  const dialog = page.getByRole('dialog', { name: '选择课程', exact: true });
  await expect(dialog).toBeVisible();
  expect((await dialog.boundingBox())!.width).toBe(375);
  await page.getByRole('button', { name: '第8单元', exact: true }).click();
  await expect(dialog.getByRole('button', { name: '选择雨点儿', exact: true })).toBeVisible();
  await page.screenshot({
    path: test.info().outputPath('word-course-picker-mobile.png'),
    fullPage: true,
  });
  await dialog.getByRole('button', { name: '选择雨点儿', exact: true }).click();
  await expect(dialog).not.toBeVisible();
  await expect(course).toBeFocused();
  await page.getByRole('checkbox', { name: '语音引导', exact: true }).setChecked(false);
  const frame = page.locator('.word-selected-picture');
  const before = await frame.boundingBox();
  await page.getByRole('button', { name: '听读彩云', exact: true }).click();
  await expect(frame).toHaveAttribute('aria-label', '词语图片：彩云');
  await expect(frame.getByRole('img')).toBeVisible();
  const after = await frame.boundingBox();
  expect(after?.height).toBe(before?.height);
  let unavailable = true;
  await page.route('**/word-illustrations/**', (route) =>
    unavailable ? route.abort() : route.continue(),
  );
  await page.getByRole('button', { name: '听读回答', exact: true }).click();
  await expect(page.locator('.word-image-failure')).toBeVisible();
  expect((await frame.boundingBox())?.height).toBe(after?.height);
  unavailable = false;
  await page.getByRole('button', { name: '重试图片', exact: true }).click();
  await expect
    .poll(() =>
      frame
        .locator('img')
        .evaluate(
          (image) =>
            (image as HTMLImageElement).complete && (image as HTMLImageElement).naturalWidth > 0,
        ),
    )
    .toBe(true);
  await expect(page.locator('.word-image-failure')).toHaveCount(0);
  await page.screenshot({ path: test.info().outputPath('word-read-mobile.png'), fullPage: true });
  await course.click();
  await page.getByRole('button', { name: '关闭选课', exact: true }).click();
  await expect(course).toBeFocused();
  await page.getByRole('button', { name: '课文背诵', exact: true }).click();
  await expect(page.locator('.word-passage')).toBeVisible();
  await expect(page.getByText('本课生字词 · 点字听读', { exact: true })).toBeVisible();
  await page.setViewportSize({ width: 1280, height: 900 });
  await page.screenshot({
    path: test.info().outputPath('word-recite-desktop.png'),
    fullPage: true,
  });
});

test('WORD-08: every local picture decodes in the browser', async ({ page, appUrl }) => {
  test.setTimeout(90000);
  await page.goto(appUrl);
  const entries = Object.values(wordImages.items);
  const bad = await page.evaluate(async (items) => {
    const failed: string[] = [];
    for (let start = 0; start < items.length; start += 12) {
      await Promise.all(
        items.slice(start, start + 12).map(async (item) => {
          const image = new Image();
          image.src = `/word-illustrations/${item.id}.svg`;
          try {
            await image.decode();
            if (!image.naturalWidth || !image.naturalHeight) failed.push(item.id);
          } catch {
            failed.push(item.id);
          }
        }),
      );
    }
    return failed;
  }, entries);
  expect(bad).toEqual([]);
  const samples = [
    '天上',
    '你的',
    '他的',
    '我们',
    '一双鞋',
    '田地',
    '火山',
    '西瓜',
    '上火',
    '下棋',
    '下马',
    '转笔刀',
    '木马',
    '天才',
    '左右',
    '一模一样',
    '独一无二',
    '三头六臂',
    '雪花飘',
    '牛羊',
    '开和关',
    '法官',
    '雨伞',
    '跳伞',
    '红灯',
    '绿灯',
    '莲子',
    '工厂',
  ];
  await page.evaluate(
    (items) => {
      const board = document.createElement('div');
      board.id = 'word-contact';
      Object.assign(board.style, {
        position: 'absolute',
        left: '0',
        top: '0',
        zIndex: '9999',
        width: '960px',
        padding: '16px',
        background: '#fffefa',
        display: 'grid',
        gridTemplateColumns: 'repeat(4,1fr)',
        gap: '12px',
      });
      for (const [word, item] of items) {
        const card = document.createElement('figure');
        card.style.margin = '0';
        const image = document.createElement('img');
        image.src = `/word-illustrations/${item.id}.svg`;
        image.style.width = '100%';
        const caption = document.createElement('figcaption');
        caption.textContent = word;
        caption.style.textAlign = 'center';
        card.append(image, caption);
        board.append(card);
      }
      document.body.append(board);
    },
    samples.map(
      (word) => [word, (wordImages.items as Record<string, { id: string }>)[word]!] as const,
    ),
  );
  await page.locator('#word-contact img').evaluateAll(async (images) => {
    await Promise.all(images.map((image) => (image as HTMLImageElement).decode()));
  });
  await page
    .locator('#word-contact')
    .screenshot({ path: test.info().outputPath('word-picture-contact.png') });
});
