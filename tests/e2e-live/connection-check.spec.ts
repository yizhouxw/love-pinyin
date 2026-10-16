import { expect } from '@playwright/test';
import { test } from '../support/real-server';

test('LAN-PERF-01: browser connection check measures existing same-origin resources without pairing', async ({
  page,
  appUrl,
}) => {
  const destinations: string[] = [];
  page.on('request', (request) => destinations.push(request.url()));
  await page.goto(appUrl + '/connection-check.html');
  await page.getByRole('button', { name: '开始检测', exact: true }).click();
  const result = page.getByRole('status');
  await expect(result).toContainText('检测完成', { timeout: 20000 });
  const text = await result.innerText();
  expect(text).toContain('请求4：');
  expect(text).toContain('gzip');
  const sizes = text.match(/传输 (\d+) 字节；解压后 (\d+) 字节/);
  expect(sizes).not.toBeNull();
  expect(Number(sizes![1])).toBeLessThan(Number(sizes![2]) / 2);
  expect(destinations.every((url) => new URL(url).origin === appUrl)).toBe(true);
  expect(destinations.some((url) => url.includes('/profiles/'))).toBe(false);
});
