import { expect, test } from '@playwright/test';

// These routed tests exercise UI logic and viewports, not real audio decoding.
// Private narration ends asynchronously; standard audio stays active so its
// explicit stop controls can be tested. Real playback has a separate product suite.
test.beforeEach(async ({ page }) => {
  await page.addInitScript(() => {
    const instances: { src: string; paused: boolean }[] = [];
    Object.defineProperty(window, '__lpAudioInstances', { value: instances });
    class MockAudio extends EventTarget {
      src: string;
      paused = true;
      preload = '';
      private generation = 0;

      constructor(source: string) {
        super();
        this.src = source;
        instances.push(this);
      }

      play() {
        this.paused = false;
        const generation = ++this.generation;
        const source = this.src;
        if (source.startsWith('/api/v1/voice/')) {
          queueMicrotask(() => {
            if (this.generation !== generation || this.paused || this.src !== source) return;
            this.paused = true;
            this.dispatchEvent(new Event('ended'));
          });
        }
        return Promise.resolve();
      }

      pause() {
        this.generation += 1;
        this.paused = true;
      }

      removeAttribute(name: string) {
        if (name === 'src') this.src = '';
      }

      load() {}
    }
    Object.defineProperty(window, 'Audio', { value: MockAudio });
  });
});

async function enterParentArea(page: import('@playwright/test').Page) {
  await page.getByRole('button', { name: '家长管理' }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
}

test('配对后可选择合法拼读候选、跳过并查看练习小结', async ({ page, isMobile }) => {
  let paired = false;
  let reset = false;
  let active = false;
  let answered = false;
  const answerRequests: { requestId: string; answerOptionId: string }[] = [];
  let skipped = false;
  let profileRevision = 0;
  let imported = false;
  let roundsSinceBreak = 0;
  let completedSessions = 0;
  let reducedMotion = false;
  let devices = [
    { id: 'device-e2e', label: '测试设备', createdAt: '2026-09-26T00:00:00Z', current: true },
    { id: 'tablet-e2e', label: '平板', createdAt: '2026-09-26T00:00:00Z', current: false },
  ];
  const exercise = {
    id: 'exercise-e2e',
    type: 'blend-choice',
    prompt: 'b 和 ā 连起来是哪一个音节？',
    options: [
      { id: 'a', label: 'bā' },
      { id: 'b', label: 'pā' },
      { id: 'c', label: 'mā' },
    ],
  };
  const skipExercise = {
    id: 'skip-exercise-e2e',
    type: 'symbol-choice',
    prompt: '再找一张拼音卡片',
    options: exercise.options,
  };
  const session = {
    id: 'session-e2e',
    lessonId: 'lesson-01',
    tasks: [
      { instanceId: 'instance-e2e', exercise },
      { instanceId: 'instance-skip-e2e', exercise: skipExercise },
    ],
    results: {},
    draftContent: true,
  };

  await page.context().route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace('/api/v1', '');
    if (path === '/local/pairing-code') {
      await route.fulfill({ json: { code: '23456789', expiresInSeconds: 300 } });
    } else if (path === '/pair') {
      paired = true;
      await route.fulfill({ json: { paired: true, isParent: true, deviceId: 'device-e2e' } });
    } else if (path === '/bootstrap') {
      await route.fulfill({
        json:
          paired && !reset
            ? {
                paired: true,
                device: { label: '测试设备', isParent: true },
                profile: {
                  id: 'profile-e2e',
                  selectedLessonId: 'lesson-01',
                  revision: profileRevision,
                  roundsSinceBreak,
                },
                attemptCount: 0,
              }
            : { paired: false, isLocalHost: true, contentVersion: 'test-v1' },
      });
    } else if (path === '/curriculum') {
      await route.fulfill({
        json: {
          inventory: {
            initials: [
              'b',
              'p',
              'm',
              'f',
              'd',
              't',
              'n',
              'l',
              'g',
              'k',
              'h',
              'j',
              'q',
              'x',
              'zh',
              'ch',
              'sh',
              'r',
              'z',
              'c',
              's',
            ],
          },
          lessons: [
            {
              id: 'lesson-01',
              order: 1,
              title: '认识拼音',
              objectives: ['认识声母和韵母'],
              knowledgeIds: ['k-e2e'],
              exerciseIds: [exercise.id, skipExercise.id],
              suggestedSessionMinutes: 5,
            },
            {
              id: 'lesson-02',
              order: 2,
              title: 'i u ü',
              objectives: ['预览后续韵母'],
              knowledgeIds: ['k-future'],
              exerciseIds: ['future-listen-only'],
              suggestedSessionMinutes: 5,
            },
          ],
          knowledgeItems: [
            {
              id: 'k-e2e',
              lessonId: 'lesson-01',
              category: 'final',
              symbol: 'ü',
              teachingNote: '看清 ü 上的两点。',
              reviewStatus: 'needs-teacher-review',
            },
            {
              id: 'k-future',
              lessonId: 'lesson-02',
              category: 'whole-syllable',
              symbol: 'zhi',
              teachingNote: '该知识点来自后续课程。',
              reviewStatus: 'needs-teacher-review',
            },
          ],
          audioRequirements: [
            {
              id: 'audio-e2e',
              knowledgeIds: ['k-future'],
              status: 'approved',
              reviewStatus: 'approved',
              file: '/audio/e2e.wav',
              sha256: 'a'.repeat(64),
              rightsEvidence: 'test-rights-reference',
              reviewEvidence: 'test-review-reference',
            },
          ],
          exercises: [
            exercise,
            skipExercise,
            {
              id: 'future-listen-only',
              type: 'listen-choice',
              prompt: '待标准音准备后练习',
              options: exercise.options,
            },
          ],
        },
      });
    } else if (path === '/audio/audio-e2e') {
      await route.fulfill({ status: 200, body: 'mock-audio', contentType: 'audio/wav' });
    } else if (path === '/profiles/progress') {
      await route.fulfill({
        json: {
          revision: profileRevision,
          selectedLessonId: 'lesson-01',
          attemptCount: 5,
          settings: { soundEnabled: true, reducedMotion },
          mastery: [
            {
              knowledgeId: 'k-e2e',
              status: 'mastered',
              reviewDue: true,
              reviewDueDate: '2026-09-26',
              sampleSize: 5,
              correctCount: 4,
              accuracy: 0.8,
              coveredModes: ['symbol-choice', 'tone-choice'],
              requiredModes: ['symbol-choice', 'tone-choice'],
            },
            {
              knowledgeId: 'k-future',
              status: 'not-started',
              reviewDue: false,
              reviewDueDate: null,
              sampleSize: 0,
              correctCount: 0,
              accuracy: null,
              coveredModes: [],
              requiredModes: ['symbol-choice'],
            },
          ],
          attempts: [
            {
              id: 'attempt-parent-1',
              knowledge_id: 'k-e2e',
              mode: 'symbol-choice',
              first_try_correct: true,
              hint_used: false,
              occurred_at: '2026-09-26T01:05:00+00:00',
              due_credit: 1,
              clock_pending: 0,
            },
            {
              id: 'attempt-parent-2',
              knowledge_id: 'k-e2e',
              mode: 'tone-choice',
              first_try_correct: false,
              hint_used: true,
              occurred_at: '2026-09-25T23:05:00+00:00',
              due_credit: 1,
              clock_pending: 0,
            },
            {
              id: 'attempt-parent-3',
              knowledge_id: 'k-e2e',
              mode: 'blend-choice',
              first_try_correct: false,
              hint_used: false,
              occurred_at: '2026-09-25T22:05:00+00:00',
              due_credit: 0,
              clock_pending: 0,
            },
            {
              id: 'attempt-parent-4',
              knowledge_id: 'k-e2e',
              mode: 'symbol-choice',
              first_try_correct: false,
              hint_used: false,
              occurred_at: '2026-09-25T21:05:00+00:00',
              due_credit: 0,
              clock_pending: 1,
            },
          ],
          completedSessions,
        },
      });
    } else if (path === '/household/settings') {
      reducedMotion = JSON.parse(route.request().postData() ?? '{}').reducedMotion;
      profileRevision += 1;
      await route.fulfill({
        json: {
          revision: profileRevision,
          selectedLessonId: 'lesson-01',
          settings: { soundEnabled: true, reducedMotion },
        },
      });
    } else if (path === '/profiles/knowledge/k-e2e/attempts') {
      const cursor = new URL(route.request().url()).searchParams.get('cursor');
      await route.fulfill({
        json: {
          knowledgeId: 'k-e2e',
          items: cursor
            ? [
                {
                  id: 'attempt-parent-5',
                  mode: 'tone-choice',
                  firstTryCorrect: true,
                  hintUsed: false,
                  dueCredit: true,
                  clockPending: false,
                  occurredAt: '2026-09-24T01:05:00+00:00',
                },
              ]
            : [
                {
                  id: 'attempt-parent-1',
                  mode: 'symbol-choice',
                  firstTryCorrect: true,
                  hintUsed: false,
                  dueCredit: true,
                  clockPending: false,
                  occurredAt: '2026-09-26T01:05:00+00:00',
                },
                {
                  id: 'attempt-parent-2',
                  mode: 'tone-choice',
                  firstTryCorrect: false,
                  hintUsed: true,
                  dueCredit: true,
                  clockPending: false,
                  occurredAt: '2026-09-25T23:05:00+00:00',
                },
                {
                  id: 'attempt-parent-3',
                  mode: 'blend-choice',
                  firstTryCorrect: false,
                  hintUsed: false,
                  dueCredit: false,
                  clockPending: false,
                  occurredAt: '2026-09-25T22:05:00+00:00',
                },
                {
                  id: 'attempt-parent-4',
                  mode: 'symbol-choice',
                  firstTryCorrect: false,
                  hintUsed: false,
                  dueCredit: false,
                  clockPending: true,
                  occurredAt: '2026-09-25T21:05:00+00:00',
                },
              ],
          nextCursor: cursor ? null : 'older-attempt',
          hasMore: !cursor,
        },
      });
    } else if (path === '/profiles/export') {
      await route.fulfill({ json: { schemaVersion: 3 } });
    } else if (path === '/profiles/import-preview') {
      await route.fulfill({
        json: {
          previewToken: 'preview-token-e2e-long-enough',
          sha256: 'a'.repeat(64),
          revision: profileRevision,
          counts: {
            sessions: 2,
            exerciseInstances: 12,
            attempts: 5,
            skippedInstances: 1,
            reviewPlans: 1,
            assessmentSummaries: 0,
          },
          willReplaceEntireHousehold: true,
        },
      });
    } else if (path === '/profiles/import') {
      imported = true;
      profileRevision += 1;
      await route.fulfill({ json: { imported: true, profile: { revision: profileRevision } } });
    } else if (path === '/profiles/reset' && route.request().method() === 'DELETE') {
      reset = true;
      paired = false;
      await route.fulfill({ json: { reset: true, pairingRequired: true } });
    } else if (path === '/devices' && route.request().method() === 'GET') {
      await route.fulfill({ json: { devices } });
    } else if (path === '/devices/tablet-e2e' && route.request().method() === 'DELETE') {
      devices = devices.filter((device) => device.id !== 'tablet-e2e');
      await route.fulfill({ json: { revoked: true, revision: 1 } });
    } else if (path === '/sessions/current') {
      await route.fulfill({
        json: active
          ? {
              ...session,
              results: {
                ...(answered
                  ? {
                      'instance-e2e': {
                        instanceId: 'instance-e2e',
                        correct: true,
                        firstTryCorrect: true,
                        hintUsed: false,
                      },
                    }
                  : {}),
                ...(skipped
                  ? {
                      'instance-skip-e2e': {
                        instanceId: 'instance-skip-e2e',
                        skipped: true,
                      },
                    }
                  : {}),
              },
            }
          : null,
      });
    } else if (path === '/sessions' && route.request().method() === 'POST') {
      active = true;
      answered = false;
      skipped = false;
      await route.fulfill({ json: session });
    } else if (path === '/instances/instance-e2e/answer') {
      answerRequests.push(route.request().postDataJSON());
      if (answerRequests.length === 1) {
        await route.abort();
        return;
      }
      answered = true;
      await route.fulfill({
        json: {
          attemptId: 'attempt-e2e',
          correct: true,
          correctOptionId: 'a',
          firstTryCorrect: true,
          hintUsed: false,
          mastery: { status: 'practicing' },
          revision: 1,
        },
      });
    } else if (path === '/instances/instance-skip-e2e/skip') {
      skipped = true;
      await route.fulfill({ json: { instanceId: 'instance-skip-e2e', skipped: true } });
    } else if (path === '/sessions/session-e2e/finish') {
      active = false;
      if (answered && skipped) {
        roundsSinceBreak = Math.min(2, roundsSinceBreak + 1);
        completedSessions += 1;
      }
      await route.fulfill({ status: 204, body: '' });
    } else if (path === '/rest/complete') {
      roundsSinceBreak = 0;
      await route.fulfill({ json: { breakRequired: false, breakCompleted: true } });
    } else {
      await route.fulfill({ status: 404, json: { detail: { code: 'NOT_FOUND' } } });
    }
  });

  await page.goto('/');
  await expect(page.getByLabel('家长配对码')).toBeVisible();
  await expect(
    page.getByText('🔒 本期练习不使用麦克风。学习记录保存在这台 Mac Studio。'),
  ).toBeVisible();
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  await page.getByLabel('家长配对码').fill('23456789');
  await page.getByRole('button', { name: '连接家庭' }).click();
  await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeVisible();
  await expect(page.getByText(/自动评分尚未通过离线验证/)).toHaveCount(0);
  await expect(page.getByText('离线评分验证中')).toHaveCount(0);
  const originalHomeViewport = page.viewportSize();
  await page.setViewportSize({ width: 320, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.getByRole('img', { name: '拼音花园已长出 0 片叶子' }).evaluate((garden) => {
    const text = garden.parentElement?.querySelectorAll('h2, p, strong');
    text?.forEach((element) => {
      const node = element as HTMLElement;
      node.dataset.originalFontSize = getComputedStyle(node).fontSize;
      node.style.fontSize = `${parseFloat(getComputedStyle(node).fontSize) * 2}px`;
    });
  });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(
    true,
  );
  await page.getByRole('img', { name: '拼音花园已长出 0 片叶子' }).evaluate((garden) => {
    garden.parentElement
      ?.querySelectorAll<HTMLElement>('[data-original-font-size]')
      .forEach((node) => {
        node.style.fontSize = node.dataset.originalFontSize ?? '';
        delete node.dataset.originalFontSize;
      });
  });
  if (originalHomeViewport) await page.setViewportSize(originalHomeViewport);
  const currentLessonTile = page.locator('.lesson-tile').first();
  if (isMobile) await currentLessonTile.tap();
  else await currentLessonTile.press('Enter');
  await expect(page.getByText('第 1 课 · 课程知识卡')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'ü' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'ü 播放标准音' })).toHaveCount(0);
  await expect(page.getByRole('button', { name: '开始本课练习' })).toBeEnabled();
  await page.getByRole('button', { name: '← 返回学习路线' }).click();
  await page.locator('.lesson-tile').nth(1).click();
  await expect(page.getByText('第 2 课 · 课程知识卡')).toBeVisible();
  const playStandardAudio = page.getByRole('button', { name: 'zhi 播放标准音' });
  await expect(playStandardAudio).toBeEnabled();
  if (isMobile) await playStandardAudio.tap();
  else await playStandardAudio.press('Enter');
  const stopStandardAudio = page.getByRole('button', { name: 'zhi 停止播放' });
  await expect(stopStandardAudio).toHaveAttribute('aria-pressed', 'true');
  expect(
    await page.evaluate(
      () =>
        (window as unknown as { __lpAudioInstances: { src: string }[] }).__lpAudioInstances[0]?.src,
    ),
  ).toBe('/api/v1/audio/audio-e2e');
  if (isMobile) await stopStandardAudio.tap();
  else await stopStandardAudio.press('Enter');
  await expect(page.getByRole('button', { name: 'zhi 播放标准音' })).toHaveAttribute(
    'aria-pressed',
    'false',
  );
  await expect(page.getByRole('button', { name: '练习资料尚未准备好' })).toBeDisabled();
  await expect(page.getByText(/请家长先把当前学习课调整到这里/)).toBeVisible();
  await page.getByRole('button', { name: '← 返回学习路线' }).click();

  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(noOverflow).toBe(true);
  await page.getByRole('button', { name: '开始今天的练习' }).click();
  await expect(page.getByRole('heading', { name: 'b 和 ā 连起来是哪一个音节？' })).toBeVisible();
  await expect(page.locator('.adult-hint')).toHaveCount(0);
  await expect(page.getByText(/暂时没有标准音频/)).toHaveCount(0);
  await expect(page.getByRole('status')).toContainText('本课目前准备了 2 道可用练习');
  await expect(page.getByText('拼读组合站')).toBeVisible();
  await expect(page.getByLabel('完整拼读候选')).toBeVisible();
  const baOption = page.getByRole('button', { name: 'A 拼读候选 bā' });
  await expect(baOption.locator('.blend-piece')).toHaveCount(2);
  await expect(baOption.locator('.blend-piece').first()).toContainText('拼音开头');
  await expect(baOption.locator('.blend-piece').last()).toContainText('韵母');
  const originalViewport = page.viewportSize();
  await page.setViewportSize({ width: 320, height: 844 });
  const smallScreen = await page.evaluate(() => ({
    contentWidth: document.documentElement.scrollWidth,
    viewportWidth: document.documentElement.clientWidth,
    targetSizes: Array.from(document.querySelectorAll('.blend-options button')).map((button) => {
      const bounds = button.getBoundingClientRect();
      return { width: Math.round(bounds.width), height: Math.round(bounds.height) };
    }),
  }));
  expect(smallScreen.contentWidth).toBeLessThanOrEqual(smallScreen.viewportWidth);
  expect(smallScreen.targetSizes.length).toBeGreaterThan(0);
  expect(smallScreen.targetSizes.every(({ width, height }) => width >= 48 && height >= 48)).toBe(
    true,
  );
  await page.evaluate(() => {
    const elements = Array.from(
      document.querySelectorAll('h1, h2, p, button, small, label, strong, li, span'),
    );
    const originalSizes = elements.map((element) => getComputedStyle(element).fontSize);
    elements.forEach((element, index) => {
      const originalSize = originalSizes[index] ?? getComputedStyle(element).fontSize;
      element.setAttribute('data-test-font-size', originalSize);
      (element as HTMLElement).style.fontSize = `${parseFloat(originalSize) * 2}px`;
    });
  });
  const zoomedScreen = await page.evaluate(() => ({
    contentWidth: document.documentElement.scrollWidth,
    viewportWidth: document.documentElement.clientWidth,
  }));
  expect(zoomedScreen.contentWidth).toBeLessThanOrEqual(zoomedScreen.viewportWidth);
  await expect(page.getByRole('heading', { name: 'b 和 ā 连起来是哪一个音节？' })).toBeVisible();
  await expect(page.getByRole('button', { name: /bā/ })).toBeVisible();
  await page.evaluate(() => {
    document.querySelectorAll('[data-test-font-size]').forEach((element) => {
      element.removeAttribute('data-test-font-size');
      (element as HTMLElement).style.fontSize = '';
    });
  });
  if (originalViewport) await page.setViewportSize(originalViewport);
  const correctCandidate = page.getByRole('button', { name: /bā/ });
  if (isMobile) await correctCandidate.tap();
  else await correctCandidate.press('Enter');
  await expect(page.getByRole('alert')).toContainText('本次操作结果未确认');
  await expect(page.getByRole('alert')).toContainText('会沿用原请求号，不会重复计分');
  await expect(page.getByRole('alert')).toBeVisible();
  await page.getByRole('button', { name: '重新连接并恢复' }).click();
  await expect.poll(() => answerRequests.length).toBe(2);
  expect(answerRequests[1]).toEqual(answerRequests[0]);
  await expect(page.getByRole('heading', { name: '再找一张拼音卡片' })).toBeVisible();
  const skip = page.getByRole('button', { name: '先跳过这题' });
  if (isMobile) await skip.tap();
  else await skip.press('Enter');

  await expect(page.getByRole('heading', { name: '今天的探索完成啦！' })).toBeVisible();
  await expect(page.getByLabel('本次练习小结')).toContainText('独立答对：1 题');
  await expect(page.getByLabel('本次练习小结')).toContainText('跳过：1 题');
  await page.getByRole('button', { name: '回到小岛' }).click();
  await expect(page.getByRole('heading', { name: '你好，小小拼音家' })).toBeVisible();
  await expect(page.getByRole('img', { name: '拼音花园已长出 1 片叶子' })).toBeVisible();
  await expect(page.getByText('1 片叶子')).toBeVisible();
  await expect(page.locator('.lesson-tile').first()).toContainText('已掌握');
  await expect(page.getByText('到期复习 · 1 项')).toBeVisible();
  await page.getByRole('button', { name: '家长管理' }).click();
  const adultDialog = page.getByRole('dialog', { name: '这里是家庭管理区' });
  await expect(adultDialog).toContainText('请把设备交给家长再继续');
  await page.getByRole('button', { name: '返回孩子学习' }).click();
  await expect(adultDialog).not.toBeVisible();
  await page.getByRole('button', { name: '家长管理' }).click();
  const adultConfirm = page.getByRole('button', { name: '我是家长，继续' });
  if (isMobile) await adultConfirm.tap();
  else await adultConfirm.press('Enter');
  await expect(page.getByRole('heading', { name: '按知识点查看进度' })).toBeVisible();
  await expect(page.getByText('录音与自动评分')).toHaveCount(0);
  await expect(page.getByText(/评分服务未通过儿童语音离线验证/)).toHaveCount(0);
  const firstLessonProgress = page.locator('.parent-lesson-progress').first();
  await firstLessonProgress.locator(':scope > summary').click();
  await expect(firstLessonProgress).toContainText('ü');
  await expect(firstLessonProgress).toContainText('已掌握');
  await expect(firstLessonProgress).toContainText('最近 5 道有效练习：独立首次答对 4 题（80%）');
  await expect(firstLessonProgress).toContainText('独立答对覆盖：字形、声调');
  await expect(firstLessonProgress).toContainText('待复习 · 2026-09-26');
  const attemptHistory = firstLessonProgress.locator('.knowledge-attempt-history');
  await attemptHistory.locator('summary').click();
  await expect(attemptHistory).toContainText('查看练习记录（已加载 4 条）');
  const recentEvents = attemptHistory.locator('ol li');
  await expect(recentEvents).toHaveCount(4);
  await expect(recentEvents.nth(0)).toContainText('字形');
  await expect(recentEvents.nth(0)).toContainText('独立首次答对');
  await expect(recentEvents.nth(1)).toContainText('声调');
  await expect(recentEvents.nth(1)).toContainText('使用过提示，未独立首次答对');
  await expect(recentEvents.nth(2)).toContainText('拼读');
  await expect(recentEvents.nth(2)).toContainText('日内重复练习，不计入掌握样本');
  await expect(recentEvents.nth(3)).toContainText('待校时，不计入掌握度');
  await attemptHistory.getByRole('button', { name: '显示更早记录' }).click();
  await expect(recentEvents).toHaveCount(5);
  const futureLessonProgress = page.locator('.parent-lesson-progress').nth(1);
  await futureLessonProgress.locator(':scope > summary').click();
  await expect(futureLessonProgress).toContainText('暂无有效练习记录 · 需要练习：字形');
  await expect(page.getByText('已连接设备')).toBeVisible();
  const reduceMotion = page.getByRole('checkbox', { name: '减少动态效果' });
  await reduceMotion.click();
  await expect(reduceMotion).toBeChecked();
  await expect
    .poll(() => page.evaluate(() => document.documentElement.dataset.reducedMotion))
    .toBe('true');
  expect(
    await page
      .locator('.device-list li')
      .first()
      .evaluate((node) => getComputedStyle(node).transitionProperty),
  ).toBe('none');
  await page.getByLabel('导入家庭备份文件').setInputFiles({
    name: 'family-backup.json',
    mimeType: 'application/json',
    buffer: Buffer.from('{"schemaVersion":3}'),
  });
  const preview = page.getByLabel('备份导入预览');
  await expect(preview).toContainText('将整体替换为 5 条练习');
  await expect(page.getByRole('button', { name: '确认替换家庭数据' })).toBeDisabled();
  await page.getByLabel('确认替换家庭学习档案文字').fill('替换家庭学习档案');
  await page.getByRole('button', { name: '确认替换家庭数据' }).click();
  await expect(page.getByRole('status')).toHaveText('家庭数据已恢复。');
  expect(imported).toBe(true);
  await expect(page.getByText('平板', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '撤销设备' }).click();
  await page.getByRole('button', { name: '确认撤销' }).click();
  await expect(page.getByText('平板', { exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: '返回学习' }).click();
  await page.getByRole('button', { name: '开始今天的练习' }).click();
  await page.getByRole('button', { name: /bā/ }).click();
  await page.getByRole('button', { name: '继续 →' }).click();
  await page.getByRole('button', { name: '先跳过这题' }).click();
  await expect(page.getByRole('heading', { name: '今天的探索完成啦！' })).toBeVisible();
  await page.getByRole('button', { name: '回到小岛' }).click();
  await expect(page.getByRole('heading', { name: '连续完成两轮啦！' })).toBeVisible();
  await expect(page.getByRole('button', { name: '结束今天的练习' })).toBeFocused();
  await page.getByRole('button', { name: '休息好了，继续学习' }).click();
  await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeVisible();
  await expect(page.getByRole('img', { name: '拼音花园已长出 2 片叶子' })).toBeVisible();
  await enterParentArea(page);
  const resetButton = page.getByRole('button', { name: '重置家庭档案' });
  await expect(resetButton).toBeDisabled();
  await page.getByLabel('确认重置家庭档案文字').fill('重置家庭档案');
  await resetButton.click();
  await expect(page.getByLabel('家长配对码')).toBeVisible();
  expect(reset).toBe(true);
});

test('首次连接家庭 Mac 失败后可在加载页原地重试', async ({ page }) => {
  let bootstrapRequests = 0;
  await page.route('**/api/v1/bootstrap', async (route) => {
    bootstrapRequests += 1;
    if (bootstrapRequests === 1) {
      await route.abort('failed');
      return;
    }
    await route.fulfill({ json: { paired: false, isLocalHost: true, contentVersion: 'test-v1' } });
  });

  await page.goto('/');
  await expect(page.getByRole('heading', { name: '暂时连不上家庭 Mac Studio' })).toBeVisible();
  await expect(page.getByRole('alert')).toContainText('暂时无法连接家庭 Mac Studio');
  await page.getByRole('button', { name: '重新连接并恢复' }).click();
  await expect(page.getByText('在 Mac 上生成家长配对码')).toBeVisible();
  expect(bootstrapRequests).toBe(2);
});

test('已撤销或过期的会话回到配对页面', async ({ page }) => {
  await page.route('**/api/v1/bootstrap', async (route) => {
    await route.fulfill({
      status: 401,
      json: { detail: { code: 'SESSION_EXPIRED' } },
    });
  });
  await page.goto('/');
  await expect(page.getByLabel('家长配对码')).toBeVisible();
  await expect(page.getByRole('heading', { name: /拼音小岛/ })).toBeVisible();
});

test('旧课程版本的当前课提示家长重选并保留学习路线', async ({ page }) => {
  let selectedLessonId = 'retired-lesson-v0';
  let revision = 7;
  await page.context().route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (path === '/bootstrap') {
      await route.fulfill({
        json: {
          paired: true,
          device: { label: '测试设备', isParent: true },
          profile: { id: 'profile-old-curriculum', selectedLessonId, revision },
          attemptCount: 1,
        },
      });
    } else if (path === '/curriculum') {
      await route.fulfill({
        json: {
          inventory: { initials: ['b'] },
          lessons: [
            {
              id: 'lesson-01',
              order: 1,
              title: '认识拼音',
              objectives: ['认识拼音符号'],
              knowledgeIds: [],
              exerciseIds: ['exercise-01'],
              suggestedSessionMinutes: 5,
            },
            {
              id: 'lesson-02',
              order: 2,
              title: '新的当前课',
              objectives: ['继续学习'],
              knowledgeIds: [],
              exerciseIds: ['exercise-02'],
              suggestedSessionMinutes: 5,
            },
          ],
          knowledgeItems: [],
          exercises: [
            { id: 'exercise-01', type: 'symbol-choice', prompt: '找一找', options: [] },
            { id: 'exercise-02', type: 'symbol-choice', prompt: '继续找一找', options: [] },
          ],
        },
      });
    } else if (path === '/profiles/progress') {
      await route.fulfill({
        json: {
          revision,
          selectedLessonId,
          completedSessions: 1,
          attemptCount: 1,
          settings: { soundEnabled: true, reducedMotion: false },
          mastery: [],
          attempts: [{ id: 'retained-attempt' }],
        },
      });
    } else if (path === '/sessions/current') {
      await route.fulfill({ json: null });
    } else if (path === '/devices' && route.request().method() === 'GET') {
      await route.fulfill({ json: { devices: [] } });
    } else if (path === '/household/current-lesson' && route.request().method() === 'PUT') {
      selectedLessonId = route.request().postDataJSON().lessonId;
      revision += 1;
      await route.fulfill({
        json: {
          selectedLessonId,
          revision,
          settings: { soundEnabled: true, reducedMotion: false },
        },
      });
    } else {
      await route.fulfill({ status: 404, json: { detail: { code: 'NOT_FOUND' } } });
    }
  });

  await page.goto('/');
  await expect(page.getByRole('heading', { name: '请选择当前课' })).toBeVisible();
  await expect(
    page.getByText(
      '保存的当前课不在此课程版本中。已有学习记录会保留，请家长重新选择学校正在学习的课程。',
    ),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: '请家长先选择当前课' })).toBeDisabled();

  await enterParentArea(page);
  await page.getByRole('combobox').selectOption('lesson-02');
  await page.locator('.inline-control button').click();
  await expect(page.getByRole('combobox')).toHaveValue('lesson-02');
  await expect(page.getByText('1 次练习记录')).toBeVisible();
  await page.getByRole('button', { name: '返回学习' }).click();
  await expect(page.getByRole('heading', { name: '第 2 课 · 新的当前课' })).toBeVisible();
  await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeEnabled();
});

test('孩子可从知识卡开始并完成两题到期复习', async ({ page }) => {
  let active: Record<string, unknown> | null = null;
  const results: Record<string, Record<string, unknown>> = {};
  const answers: string[] = [];
  let finished = false;
  const first = {
    id: 'review-exercise-1',
    type: 'tone-choice',
    prompt: 'ā 是第几声？',
    options: [
      { id: 'first-tone', label: 'ā' },
      { id: 'second-tone', label: 'á' },
    ],
  };
  const second = {
    id: 'review-exercise-2',
    type: 'symbol-choice',
    prompt: '找出带一声的拼音',
    options: [
      { id: 'first-tone', label: 'mā' },
      { id: 'second-tone', label: 'má' },
    ],
  };
  const reviewSession = {
    id: 'review-session-e2e',
    reviewKnowledgeId: 'k-review',
    tasks: [
      { instanceId: 'review-instance-1', exercise: first },
      { instanceId: 'review-instance-2', exercise: second },
    ],
    results,
    draftContent: true,
  };

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (path === '/bootstrap') {
      await route.fulfill({
        json: {
          paired: true,
          device: { label: '孩子平板', isParent: false },
          profile: {
            id: 'review-profile',
            selectedLessonId: 'lesson-01',
            revision: 4,
            roundsSinceBreak: 0,
          },
        },
      });
    } else if (path === '/curriculum') {
      await route.fulfill({
        json: {
          inventory: { initials: ['m'] },
          lessons: [
            {
              id: 'lesson-01',
              order: 1,
              title: '认识拼音',
              objectives: ['认识拼音和声调'],
              knowledgeIds: ['k-review'],
              exerciseIds: [first.id, second.id],
              suggestedSessionMinutes: 5,
            },
          ],
          knowledgeItems: [
            {
              id: 'k-review',
              lessonId: 'lesson-01',
              category: 'tone',
              symbol: 'ā',
              teachingNote: '观察声调符号。',
              reviewStatus: 'needs-teacher-review',
            },
          ],
          exercises: [first, second],
        },
      });
    } else if (path === '/profiles/progress') {
      await route.fulfill({
        json: {
          revision: 4,
          selectedLessonId: 'lesson-01',
          settings: { soundEnabled: true, reducedMotion: false },
          mastery: [
            {
              knowledgeId: 'k-review',
              status: 'mastered',
              reviewDue: true,
              reviewDueDate: '2026-09-26',
              sampleSize: 5,
              correctCount: 5,
            },
          ],
          attempts: [],
          completedSessions: 0,
          reviewRecommendations: [
            {
              knowledgeId: 'k-review',
              symbol: 'ā',
              lessonId: 'lesson-01',
              lessonTitle: '认识拼音',
              dueDate: '2026-09-26',
              overdueDays: 0,
            },
          ],
        },
      });
    } else if (path === '/sessions/current') {
      await route.fulfill({ json: active ? { ...reviewSession, results } : null });
    } else if (path === '/reviews/k-review/sessions' && route.request().method() === 'POST') {
      for (const key of Object.keys(results)) delete results[key];
      active = reviewSession;
      await route.fulfill({ json: reviewSession });
    } else if (/^\/instances\/review-instance-[12]\/answer$/.test(path)) {
      const instanceId = path.includes('review-instance-1')
        ? 'review-instance-1'
        : 'review-instance-2';
      const answer = route.request().postDataJSON();
      answers.push(answer.answerOptionId);
      results[instanceId] = {
        instanceId,
        answerOptionId: answer.answerOptionId,
        correctOptionId: 'first-tone',
        correct: answer.answerOptionId === 'first-tone',
        firstTryCorrect: answer.answerOptionId === 'first-tone',
        hintUsed: false,
        mastery: { status: 'mastered' },
      };
      await route.fulfill({ json: results[instanceId] });
    } else if (path === '/sessions/review-session-e2e/finish') {
      finished = true;
      active = null;
      await route.fulfill({ json: { finished: true, completedRound: true } });
    } else {
      await route.fulfill({ status: 404, json: { detail: { code: 'NOT_FOUND' } } });
    }
  });

  await page.goto('/');
  await page.locator('.lesson-tile').first().click();
  await expect(page.getByRole('heading', { name: 'ā' })).toBeVisible();
  await page.getByRole('button', { name: '开始两题复习' }).click();
  await expect(page.getByText('拼音小岛 · 两题复习')).toBeVisible();
  await expect(page.getByRole('heading', { name: first.prompt })).toBeVisible();
  await page.locator('.options button').first().click();
  await page.getByRole('button', { name: '继续 →' }).click();
  await expect(page.getByRole('heading', { name: second.prompt })).toBeVisible();
  await page.locator('.options button').first().click();
  await page.getByRole('button', { name: '继续 →' }).click();
  await expect(page.getByRole('heading', { name: '今天的探索完成啦！' })).toBeVisible();
  await expect(page.getByLabel('本次练习小结')).toContainText('独立答对：2 题');
  await page.getByRole('button', { name: '回到小岛' }).click();
  await expect(page.getByRole('heading', { name: '你好，小小拼音家' })).toBeVisible();
  await expect(page.getByRole('heading', { name: '今日推荐复习' })).toBeVisible();
  await page.getByRole('button', { name: '开始复习 →' }).click();
  await expect(page.getByText('拼音小岛 · 两题复习')).toBeVisible();
  expect(answers).toEqual(['first-tone', 'first-tone']);
  expect(finished).toBe(true);
});

test('家长校时后可明确保留待校时练习为不计分记录', async ({ page }) => {
  let pendingClockAttempts = 1;
  let resolvedBody: Record<string, unknown> | null = null;
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname.replace('/api/v1', '');
    if (path === '/bootstrap') {
      await route.fulfill({
        json: {
          paired: true,
          device: { label: '家长设备', isParent: true },
          profile: {
            id: 'clock-profile',
            selectedLessonId: 'lesson-01',
            revision: 8,
            roundsSinceBreak: 0,
          },
        },
      });
    } else if (path === '/curriculum') {
      await route.fulfill({
        json: {
          inventory: { initials: [] },
          lessons: [
            {
              id: 'lesson-01',
              order: 1,
              title: '认识拼音',
              objectives: ['认识拼音'],
              knowledgeIds: [],
              exerciseIds: [],
              suggestedSessionMinutes: 5,
            },
          ],
          knowledgeItems: [],
          exercises: [],
        },
      });
    } else if (path === '/profiles/progress') {
      await route.fulfill({
        json: {
          revision: 8,
          selectedLessonId: 'lesson-01',
          completedSessions: 0,
          clockSkewDetected: false,
          pendingClockAttempts,
          settings: { soundEnabled: true, reducedMotion: false },
          mastery: [],
          attempts: [],
        },
      });
    } else if (path === '/sessions/current') {
      await route.fulfill({ json: null });
    } else if (path === '/devices') {
      await route.fulfill({ json: { devices: [] } });
    } else if (path === '/profiles/clock-pending/resolve') {
      resolvedBody = route.request().postDataJSON();
      pendingClockAttempts = 0;
      await route.fulfill({ json: { resolved: 1, resolution: 'keep-unscored' } });
    } else {
      await route.fulfill({ status: 404, json: { detail: { code: 'NOT_FOUND' } } });
    }
  });

  await page.goto('/');
  await enterParentArea(page);
  await expect(
    page.getByText('系统时间已恢复。请决定如何处理待校时练习；保留的记录始终不计入掌握度。'),
  ).toBeVisible();
  await expect(page.getByRole('button', { name: '保留为不计分练习' })).toBeDisabled();
  await page.getByLabel('确认处理待校时练习').fill('保留为不计分练习');
  await page.getByRole('button', { name: '保留为不计分练习' }).click();
  await expect(
    page.getByText('系统时间已恢复。请决定如何处理待校时练习；保留的记录始终不计入掌握度。'),
  ).toHaveCount(0);
  expect(resolvedBody).toEqual({
    resolution: 'keep-unscored',
    confirmation: '保留为不计分练习',
  });
});
