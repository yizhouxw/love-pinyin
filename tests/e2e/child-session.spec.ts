import { expect, test } from '@playwright/test';

test('配对后可用键盘或触摸跳过题目并查看练习小结', async ({ page, isMobile }) => {
  let paired = false;
  let active = false;
  let skipped = false;
  let devices = [
    { id: 'device-e2e', label: '测试设备', createdAt: '2026-09-26T00:00:00Z', current: true },
    { id: 'tablet-e2e', label: '平板', createdAt: '2026-09-26T00:00:00Z', current: false },
  ];
  const exercise = {
    id: 'exercise-e2e',
    type: 'symbol-choice',
    prompt: '哪一个是声母？',
    options: [
      { id: 'a', label: 'b' },
      { id: 'b', label: 'a' },
    ],
    answer: { optionId: 'a' },
  };
  const session = {
    id: 'session-e2e',
    lessonId: 'lesson-01',
    tasks: [{ instanceId: 'instance-e2e', exercise }],
    results: {},
    draftContent: true,
  };

  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url());
    const path = url.pathname.replace('/api/v1', '');
    if (path === '/local/pairing-code') {
      await route.fulfill({ json: { code: '23456789', expiresInSeconds: 300 } });
    } else if (path === '/pair') {
      paired = true;
      await route.fulfill({ json: { paired: true, isParent: true, deviceId: 'device-e2e' } });
    } else if (path === '/bootstrap') {
      await route.fulfill({
        json: paired
          ? {
              paired: true,
              device: { label: '测试设备', isParent: true },
              profile: { id: 'profile-e2e', selectedLessonId: 'lesson-01', revision: 0 },
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
              exerciseIds: [exercise.id],
              suggestedSessionMinutes: 5,
            },
          ],
        },
      });
    } else if (path === '/profiles/progress') {
      await route.fulfill({
        json: {
          revision: 0,
          selectedLessonId: 'lesson-01',
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
              results: skipped
                ? { 'instance-e2e': { instanceId: 'instance-e2e', skipped: true } }
                : {},
            }
          : null,
      });
    } else if (path === '/sessions' && route.request().method() === 'POST') {
      active = true;
      await route.fulfill({ json: session });
    } else if (path === '/instances/instance-e2e/skip') {
      skipped = true;
      await route.fulfill({ json: { instanceId: 'instance-e2e', skipped: true } });
    } else if (path === '/sessions/session-e2e/finish') {
      active = false;
      await route.fulfill({ status: 204, body: '' });
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

  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(noOverflow).toBe(true);
  await page.getByRole('button', { name: '开始今天的练习' }).click();
  await expect(page.getByRole('heading', { name: '哪一个是声母？' })).toBeVisible();
  const skip = page.getByRole('button', { name: '先跳过这题' });
  if (isMobile) await skip.tap();
  else await skip.press('Enter');

  await expect(page.getByRole('heading', { name: '今天的探索完成啦！' })).toBeVisible();
  await expect(page.getByLabel('本次练习小结')).toContainText('跳过：1 题');
  await page.getByRole('button', { name: '回到小岛' }).click();
  await expect(page.getByRole('heading', { name: '你好，小小拼音家' })).toBeVisible();
  await expect(page.locator('.lesson-tile')).toContainText('已掌握');
  await expect(page.getByText('到期复习 · 1 项')).toBeVisible();
  await page.getByRole('button', { name: '家长管理' }).click();
  await expect(page.getByText('已连接设备')).toBeVisible();
  await expect(page.getByText('平板', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: '撤销设备' }).click();
  await page.getByRole('button', { name: '确认撤销' }).click();
  await expect(page.getByText('平板', { exact: true })).toHaveCount(0);
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
