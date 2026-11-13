import { expect, type Page } from '@playwright/test';

async function chooseLesson(page: Page, title: string) {
  await page.getByRole('button', { name: /^选择课程/ }).click();
  await page
    .getByRole('dialog')
    .getByRole('button', { name: `选择${title}`, exact: true })
    .click();
}
import { test } from '../support/real-server';
import { pairForHouseholdMaterial, useHouseholdMaterial } from '../support/household-material';
import wordImages from '../../content/word-practice/images.json' with { type: 'json' };

test.use({ selectedPinyinSource: true });

test('WORD-01/02/03: real voices, hidden dictation, text highlights and device practice', async ({
  page,
  appUrl,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (error) => errors.push(error.message));
  await pairForHouseholdMaterial(page, appUrl);
  await page.getByRole('button', { name: '进入词语天天练 →' }).click();
  await expect(page.getByRole('button', { name: '选择课程，当前天地人' })).toBeVisible();
  await page.getByRole('button', { name: '返回首页' }).click();
  await useHouseholdMaterial(page);
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
  await pairForHouseholdMaterial(page, appUrl);
  await useHouseholdMaterial(page);
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
  await pairForHouseholdMaterial(page, appUrl);
  await useHouseholdMaterial(page);
  await page.getByRole('button', { name: '进入词语天天练 →' }).click();
  await page.getByLabel('播放设置', { exact: true }).click();
  const guidance = page.getByRole('checkbox', { name: '语音引导', exact: true });
  if (!(await guidance.isVisible())) await page.getByLabel('播放设置', { exact: true }).click();
  await guidance.setChecked(false);
  await page.getByRole('button', { name: '完成', exact: true }).click();
  let instructions = 0;
  page.on('request', (request) => {
    if (request.url().includes('/voice/word-ui-')) instructions++;
  });
  await page.getByRole('button', { name: '词语听写', exact: true }).click();
  await page.getByRole('button', { name: '词语拼读', exact: true }).click();
  expect(instructions).toBe(0);
  if (!(await guidance.isVisible())) await page.getByLabel('播放设置', { exact: true }).click();
  await guidance.setChecked(true);
  await page.getByRole('button', { name: '完成', exact: true }).click();
  const automatic = page.waitForResponse(
    (response) => response.url().includes('/voice/word-ui-write') && response.ok(),
  );
  await page.getByRole('button', { name: '词语听写', exact: true }).click();
  await automatic;
  if (!(await guidance.isVisible())) await page.getByLabel('播放设置', { exact: true }).click();
  await guidance.setChecked(false);
  await page.getByRole('button', { name: '完成', exact: true }).click();
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
  await page.route('**/api/v1/voice/word-say-*', (route) => route.abort());
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
  await pairForHouseholdMaterial(page, appUrl);
  await useHouseholdMaterial(page);
  await expect(page.locator('.practice-entries strong')).toHaveText([
    '天天练拼音',
    '词语天天练',
    '拼音游戏乐园',
  ]);
  for (const width of [320, 375, 820, 1280]) {
    await page.setViewportSize({ width, height: 680 });
    for (const entry of [
      '开始今天的练习',
      '课堂学习',
      '进入天天练拼音',
      '进入词语天天练 →',
      '进入游戏乐园',
    ]) {
      const button = page.getByRole('button', { name: entry, exact: true });
      const frame = (await button.boundingBox())!;
      expect(frame.height).toBeGreaterThanOrEqual(44);
      expect(frame.x + frame.width).toBeLessThanOrEqual(width);
      expect(frame.y + frame.height).toBeLessThanOrEqual(680);
    }
  }
  await page.setViewportSize({ width: 375, height: 812 });
  await page.getByRole('button', { name: '进入词语天天练 →' }).click();
  const course = page.getByRole('button', { name: /^选择课程/ });
  expect((await page.locator('.word-header').boundingBox())!.height).toBeLessThanOrEqual(64);
  const settings = page.getByLabel('播放设置', { exact: true });
  expect((await settings.boundingBox())!.height).toBeGreaterThanOrEqual(48);
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
  await settings.click();
  await page.getByRole('checkbox', { name: '语音引导', exact: true }).setChecked(false);
  await page.getByRole('button', { name: '完成', exact: true }).click();
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

test('DIST-07/08/WORD-10/DAILY-13: integrated settings and real direct and spelling audio', async ({
  page,
  appUrl,
}, info) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await pairForHouseholdMaterial(page, appUrl);
  await page.getByRole('button', { name: '家长管理', exact: true }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  const panel = page.locator('.parent-panel').filter({
    has: page.getByRole('heading', { name: '学习与隐私设置', exact: true }),
  });
  const advanced = panel.locator('.material-settings');
  const controls = panel.locator(
    ':scope > h3, :scope > details > summary, :scope > button, .version-trigger',
  );
  const labels = await controls.allTextContents();
  const expectedOrder = [
    '学习与体验',
    '声音与播放设置',
    '设备与数据',
    '备份与恢复',
    '高级设置',
    '删除与重置',
    '退出此设备配对',
    '信息与记录',
    '详细学习记录',
    '音频状态',
    '音频来源与许可',
  ];
  expect(labels.filter((label) => expectedOrder.includes(label))).toEqual(expectedOrder);
  await expect(panel.locator(':scope > :last-child .version-trigger')).toBeVisible();
  await expect(advanced).not.toHaveAttribute('open', '');
  await advanced.getByText('高级设置', { exact: true }).click();
  await expect(advanced.getByRole('combobox', { name: '学习素材' })).toHaveValue('original');
  await expect(panel.getByText('CC-BY-SA-3.0', { exact: true })).toBeHidden();
  await panel.getByText('音频来源与许可', { exact: true }).click();
  await expect(panel.getByText('CC-BY-SA-3.0', { exact: true })).toBeVisible();
  await panel.screenshot({ path: info.outputPath('material-settings.png') });
  await page.getByRole('button', { name: '返回学习', exact: true }).click();
  await page.getByRole('button', { name: '进入词语天天练 →' }).click();

  await expect(page.getByRole('button', { name: '连读本课' })).toBeInViewport();
  await expect(page.getByRole('button', { name: '直接读', exact: true })).toBeHidden();
  await expect(page.getByRole('button', { name: /^间隔设置/ })).toBeHidden();
  await page.getByRole('button', { name: '拓展朗读', exact: true }).click();
  await expect(page.getByText('身边的人', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: '听全文' })).toBeVisible();
  await expect(page.getByRole('button', { name: '隐藏短文', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '词语拼读', exact: true }).click();
  await page.getByLabel('播放设置', { exact: true }).click();
  await expect(page.getByRole('button', { name: /^间隔设置/ })).toBeVisible();
  await page.getByRole('button', { name: /^选择课程/ }).click();
  const picker = page.getByRole('dialog');
  await picker.getByRole('button', { name: '第6单元', exact: true }).click();
  await picker.getByRole('button', { name: '选择语文园地六', exact: true }).click();
  const word = page.getByRole('button', { name: '听读老师', exact: true });
  await expect(word.locator('.pinyin-whole')).toHaveText('shī');
  const color = await word
    .locator('.pinyin-whole')
    .evaluate((element) => getComputedStyle(element).color);
  expect(color).toBe('rgb(32, 78, 145)');
  await page.getByLabel('播放设置', { exact: true }).click();
  await expect(page.getByRole('button', { name: '直接读', exact: true })).toHaveAttribute(
    'aria-pressed',
    'true',
  );
  await page.getByRole('button', { name: '完成', exact: true }).click();
  const direct = page.waitForResponse(
    (response) => /\/voice\/word-say-c9a31a3f670b7f99$/.test(response.url()) && response.ok(),
  );
  await word.click();
  await direct;
  const spelling = page.waitForResponse(
    (response) => response.url().endsWith('/daily-audio/spelling-shi1') && response.ok(),
  );
  const initial = page.waitForResponse(
    (response) => response.url().endsWith('/audio/original-audio-initial-l') && response.ok(),
  );
  await page.getByLabel('播放设置', { exact: true }).click();
  await page.getByRole('button', { name: '拼读', exact: true }).click();
  await page.getByRole('button', { name: '完成', exact: true }).click();
  await expect(page.locator('.word-playback')).not.toContainText('正在播放');
  await word.click();
  const [, initialAudio] = await Promise.all([spelling, initial]);
  expect(initialAudio.headers()['content-type']).toBe('audio/wav');
  await expect(page.locator('.word-playback')).not.toContainText('正在播放', { timeout: 15000 });
  await expect(page.locator('.word-audio-error')).toHaveAttribute('aria-hidden', 'true');
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.locator('.word-practice').screenshot({ path: info.outputPath('word-spelling.png') });

  await page.getByRole('button', { name: '返回首页' }).click();
  await useHouseholdMaterial(page);
  await page.getByRole('button', { name: '进入天天练拼音' }).click();
  await page.getByRole('button', { name: '第 3 份', exact: true }).click();
  await page.getByRole('button', { name: /读词语/ }).click();
  await page.getByLabel('播放设置', { exact: true }).click();
  await page.getByRole('checkbox', { name: '语音引导' }).uncheck();
  await expect(page.locator('.daily-target')).toContainText('bà');
  const dailyComponent = page.waitForResponse(
    (response) => response.url().endsWith('/audio/audio-initial-b') && response.ok(),
  );
  await page.getByRole('button', { name: '拼读', exact: true }).click();
  await page.getByRole('button', { name: '完成', exact: true }).click();
  await page.getByRole('button', { name: '开始跟读' }).click();
  await dailyComponent;
  await expect(page.locator('.daily-status-strip')).toContainText('轮到你读啦', { timeout: 15000 });
  await expect(page.getByRole('button', { name: '重试示范' })).toHaveCount(0);
});

test('WORD-14: dictation actions and settings stay together', async ({ page, appUrl }) => {
  await page.goto(appUrl);
  await page.getByRole('button', { name: '访客体验', exact: true }).click();
  await page.getByRole('button', { name: '进入词语天天练 →' }).click();
  await page.getByRole('button', { name: /^选择课程/ }).click();
  const picker = page.getByRole('dialog');
  await picker.getByRole('button', { name: '第5单元', exact: true }).click();
  await picker.getByRole('button', { name: '选择江南', exact: true }).click();
  await page.getByRole('button', { name: '词语听写', exact: true }).click();

  const card = page.locator('.word-dictation');
  const listen = card.getByRole('button', { name: /听词语/ });
  const reveal = card.locator('.word-reveal');
  const settings = page.getByLabel('播放设置', { exact: true });
  const figure = card.getByRole('figure');
  await expect(card.getByRole('button', { name: '停止播放' })).toBeVisible();
  await expect(page.getByRole('checkbox', { name: '语音引导' })).toBeHidden();

  for (const width of [1280, 390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect(listen).toBeInViewport();
    await expect(reveal).toBeInViewport();
    if (width < 600) {
      expect((await reveal.boundingBox())!.y).toBeLessThan((await figure.boundingBox())!.y);
    }
    const cardBounds = (await card.boundingBox())!;
    const settingsBounds = (await settings.boundingBox())!;
    expect(settingsBounds.y).toBeGreaterThanOrEqual(cardBounds.y);
    expect(settingsBounds.y + settingsBounds.height).toBeLessThanOrEqual(
      cardBounds.y + cardBounds.height,
    );
    await expect(page.locator('.word-options')).toHaveCount(0);
    await expect(
      page.locator('.word-header').getByLabel('玩法与提示', { exact: true }),
    ).toBeVisible();
    for (const zoom of ['100%', '200%']) {
      await page.evaluate((size) => (document.documentElement.style.fontSize = size), zoom);
      const answer = card.locator('.word-answer');
      const height = (await answer.boundingBox())!.height;
      await expect(figure.getByRole('img')).toHaveCount(0);
      await reveal.press('Enter');
      await expect(reveal).toBeFocused();
      expect(
        await answer
          .locator('ruby')
          .evaluate((ruby) => parseFloat(getComputedStyle(ruby).fontSize)),
      ).toBeGreaterThanOrEqual(32);
      expect(
        await answer.locator('rt').evaluate((rt) => parseFloat(getComputedStyle(rt).fontSize)),
      ).toBeGreaterThanOrEqual(19);
      await expect(figure.getByRole('img')).toBeVisible();
      expect((await answer.boundingBox())!.height).toBe(height);
      expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(width);
      if (zoom === '100%')
        await card.screenshot({ path: test.info().outputPath(`dictation-${width}.png`) });
      await reveal.press('Enter');
    }
    await page.evaluate(() => (document.documentElement.style.fontSize = ''));
  }
});

test('快捷设置覆盖内容、Escape 返回入口并保留即时偏好', async ({ page, appUrl }) => {
  await pairForHouseholdMaterial(page, appUrl);
  await page.getByRole('button', { name: '进入词语天天练 →' }).click();
  const trigger = page.getByLabel('播放设置', { exact: true });
  const content = page.locator('.word-header');
  for (const width of [1280, 390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await trigger.scrollIntoViewIfNeeded();
    const before = await content.boundingBox();
    await trigger.click();
    await expect(page.locator('.word-settings .quick-settings-panel')).toBeVisible();
    expect(await content.boundingBox()).toEqual(before);
    const bounds = (await page.locator('.word-settings .quick-settings-panel').boundingBox())!;
    expect(bounds.x).toBeGreaterThanOrEqual(0);
    expect(bounds.x + bounds.width).toBeLessThanOrEqual(width);
    await page.screenshot({ path: test.info().outputPath(`settings-${width}.png`) });
    const guidance = page.getByRole('checkbox', { name: '语音引导', exact: true });
    if (!(await guidance.isVisible())) await page.getByLabel('播放设置', { exact: true }).click();
    await guidance.setChecked(false);
    await page.keyboard.press('Escape');
    await expect(trigger).toBeFocused();
    await expect(page.locator('.word-settings .quick-settings-panel')).toBeHidden();
    await trigger.click();
    await expect(guidance).not.toBeChecked();
    await page.getByRole('button', { name: '完成', exact: true }).click();
  }
});
