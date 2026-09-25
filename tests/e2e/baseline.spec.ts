import { expect, test } from '@playwright/test';

test('开发基线在各浏览器和视口可显示并交互', async ({ page, isMobile, browserName }) => {
  await page.goto('/');
  await expect(page.getByRole('heading', { name: '爱拼音', exact: true })).toBeVisible();
  await expect(page.getByRole('button')).toHaveCSS('min-height', '52px');
  const noOverflow = await page.evaluate(
    () => document.documentElement.scrollWidth <= window.innerWidth,
  );
  expect(noOverflow).toBe(true);
  if (isMobile) await page.getByRole('button').tap();
  else {
    // macOS Safari defaults to Option+Tab for all controls.
    await page.keyboard.press(
      browserName === 'webkit' && process.platform === 'darwin' ? 'Alt+Tab' : 'Tab',
    );
    await expect(page.getByRole('button')).toBeFocused();
    await page.keyboard.press('Enter');
  }
  await expect(page.getByRole('status')).toHaveText('交互验证成功');
});
