import { expect } from '@playwright/test';
import { test } from '../support/real-server';

test('MAC-05: native window connects, restores an expired session and reconnects after reset', async ({
  page,
  context,
  appUrl,
}) => {
  await page.addInitScript(() => {
    (window as Window & { __LOVE_PINYIN_MAC_APP__?: boolean }).__LOVE_PINYIN_MAC_APP__ = true;
  });
  await page.goto(appUrl);
  await expect(page.getByRole('button', { name: '课堂学习' })).toBeVisible();
  await expect(page.getByLabel('家长配对码')).toHaveCount(0);
  await context.clearCookies();
  await page.reload();
  await expect(page.getByRole('button', { name: '课堂学习' })).toBeVisible();
  const result = await page.evaluate(async () => {
    const csrf = document.cookie
      .split('; ')
      .find((item) => item.startsWith('lp_csrf='))!
      .slice(8);
    const response = await fetch('/api/v1/profiles/reset', {
      method: 'DELETE',
      headers: { 'Content-Type': 'application/json', 'X-LP-CSRF': decodeURIComponent(csrf) },
      body: JSON.stringify({ confirmation: '重置家庭档案' }),
    });
    return response.status;
  });
  expect(result).toBe(200);
  await page.reload();
  await expect(page.getByRole('button', { name: '课堂学习' })).toBeVisible();
});
