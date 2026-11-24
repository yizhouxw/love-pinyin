import { expect, test } from '@playwright/test';

test('原生容器区分普通内容与家长文本框的长按行为', async ({ page }, info) => {
  test.skip(!['phone-chromium', 'phone-webkit', 'tablet-webkit'].includes(info.project.name));
  await page.addInitScript((android) => {
    if (android) {
      Object.assign(window, { __lovePinyinAndroid: true, LovePinyinAndroid: { postMessage() {} } });
    } else {
      Object.assign(window, {
        __lovePinyinIOS: true,
        webkit: { messageHandlers: { learning: { postMessage: async () => null } } },
      });
    }
  }, info.project.name === 'phone-chromium');
  await page.goto('/');
  await expect(page.locator('html')).toHaveAttribute('data-ios-app', '');
  const result = await page.evaluate(() => {
    const sample = document.createElement('section');
    sample.innerHTML =
      '<span>课程</span><img alt="插图"><input readonly value="123456"><textarea></textarea>';
    document.body.append(sample);
    return Array.from(sample.children).map((element) => ({
      selection: getComputedStyle(element).getPropertyValue('-webkit-user-select'),
      menuAllowed: element.dispatchEvent(
        new MouseEvent('contextmenu', { bubbles: true, cancelable: true }),
      ),
    }));
  });
  expect(result).toEqual([
    { selection: 'none', menuAllowed: false },
    { selection: 'none', menuAllowed: false },
    { selection: 'text', menuAllowed: true },
    { selection: 'text', menuAllowed: true },
  ]);
});
