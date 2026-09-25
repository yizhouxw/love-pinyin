import { expect, test } from '@playwright/test';

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
    } else if (path === '/profiles/progress') {
      await route.fulfill({
        json: {
          revision: profileRevision,
          selectedLessonId: 'lesson-01',
          settings: { soundEnabled: true, reducedMotion },
          mastery: [
            {
              knowledgeId: 'k-e2e',
              status: 'mastered',
              reviewDue: true,
              reviewDueDate: '2026-09-26',
              sampleSize: 5,
              correctCount: 4,
            },
          ],
          attempts: [],
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
      if (answered && skipped) roundsSinceBreak = Math.min(2, roundsSinceBreak + 1);
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
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  await page.getByLabel('家长配对码').fill('23456789');
  await page.getByRole('button', { name: '连接家庭' }).click();
  await expect(page.getByRole('button', { name: '开始今天的练习' })).toBeVisible();
  const currentLessonTile = page.locator('.lesson-tile').first();
  if (isMobile) await currentLessonTile.tap();
  else await currentLessonTile.press('Enter');
  await expect(page.getByText('第 1 课 · 课程知识卡')).toBeVisible();
  await expect(page.getByRole('heading', { name: 'ü' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'ü 标准音待准备' })).toBeDisabled();
  await expect(page.getByRole('button', { name: '开始本课视觉练习' })).toBeEnabled();
  await page.getByRole('button', { name: '← 返回学习路线' }).click();
  await page.locator('.lesson-tile').nth(1).click();
  await expect(page.getByText('第 2 课 · 课程知识卡')).toBeVisible();
  await expect(page.getByRole('button', { name: '练习资料尚未准备好' })).toBeDisabled();
  await expect(page.getByText(/请家长先把当前学习课调整到这里/)).toBeVisible();
  await page.getByRole('button', { name: '← 返回学习路线' }).click();

  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(noOverflow).toBe(true);
  await page.getByRole('button', { name: '开始今天的练习' }).click();
  await expect(page.getByRole('heading', { name: 'b 和 ā 连起来是哪一个音节？' })).toBeVisible();
  await expect(page.getByText('拼读组合站')).toBeVisible();
  await expect(page.getByLabel('完整拼读候选')).toBeVisible();
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
  await expect(page.getByRole('alert')).toBeVisible();
  await page.reload();
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
  await expect(page.locator('.lesson-tile').first()).toContainText('已掌握');
  await expect(page.getByText('到期复习 · 1 项')).toBeVisible();
  await page.getByRole('button', { name: '家长管理' }).click();
  await expect(page.getByText('已连接设备')).toBeVisible();
  const reduceMotion = page.getByRole('checkbox');
  await reduceMotion.check();
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
  await page.getByRole('button', { name: '家长管理' }).click();
  const resetButton = page.getByRole('button', { name: '重置家庭档案' });
  await expect(resetButton).toBeDisabled();
  await page.getByLabel('确认重置家庭档案文字').fill('重置家庭档案');
  await resetButton.click();
  await expect(page.getByLabel('家长配对码')).toBeVisible();
  expect(reset).toBe(true);
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
