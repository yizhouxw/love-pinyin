import { expect } from '@playwright/test';
import { test } from '../support/real-server';

test.use({ selectedPinyinSource: true });
test('KEY-01: keyboard works after start, mouse actions and voice; held keys stop on keyup; buttons keep native Space', async ({
  page,
  appUrl,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto(appUrl);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭' }).click();
  await page.getByRole('button', { name: '进入游戏乐园' }).click();
  await page.getByRole('button', { name: '开始星际投递' }).click();
  const stage = page.locator('.scene-stage');
  await page.getByRole('button', { name: '听拼音', exact: true }).click();
  await expect(page.getByRole('button', { name: '发射 ↑', exact: true })).toBeEnabled({
    timeout: 15000,
  });
  const before = Number(await stage.getAttribute('data-world-x'));
  await page.keyboard.press('ArrowLeft');
  await expect
    .poll(async () => Number(await stage.getAttribute('data-world-x')))
    .toBeLessThan(before);
  await page.getByRole('button', { name: '瞄准 →', exact: true }).click();
  const afterMouse = Number(await stage.getAttribute('data-world-x'));
  await page.keyboard.press('a');
  expect(Number(await stage.getAttribute('data-world-x'))).toBeLessThan(afterMouse);
  const heldStart = Number(await stage.getAttribute('data-world-x'));
  await page.keyboard.down('d');
  await page.waitForTimeout(650);
  await page.keyboard.up('d');
  const heldEnd = Number(await stage.getAttribute('data-world-x'));
  expect(heldEnd - heldStart).toBeGreaterThan(50);
  await page.waitForTimeout(450);
  expect(Number(await stage.getAttribute('data-world-x'))).toBe(heldEnd);
  await page.keyboard.press('p');
  await expect(page.getByRole('button', { name: '▶ 继续游戏', exact: true })).toBeVisible();
  const paused = await stage.getAttribute('data-world-distance');
  await page.waitForTimeout(200);
  expect(await stage.getAttribute('data-world-distance')).toBe(paused);
  await page.keyboard.press('p');
  await expect(page.getByRole('button', { name: '发射 ↑', exact: true })).toBeEnabled();
  // A keyboard user can still focus a voice button and activate it with Space.
  await page.getByRole('button', { name: '听本关故事', exact: true }).focus();
  await page.keyboard.press('Space');
  await expect(page.getByRole('button', { name: '停止听本关故事', exact: true })).toBeVisible();
  await page.getByRole('button', { name: '听拼音', exact: true }).click();
  await expect(page.getByRole('button', { name: '发射 ↑', exact: true })).toBeEnabled({
    timeout: 15000,
  });
  const afterAudio = Number(await stage.getAttribute('data-world-x'));
  await page.keyboard.press('ArrowLeft');
  expect(Number(await stage.getAttribute('data-world-x'))).toBeLessThan(afterAudio);
  await page.getByRole('button', { name: '保存并退出游戏' }).click();
  const scroll = await page.evaluate(() => scrollY);
  await page.keyboard.press('ArrowDown');
  expect(await page.evaluate(() => scrollY)).toBeGreaterThanOrEqual(scroll);
  expect(errors).toEqual([]);
});
