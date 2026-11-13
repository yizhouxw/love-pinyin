import { expect, type Page } from '@playwright/test';
import { test } from '../support/real-server';
import curriculum from '../../content/curriculum.json' with { type: 'json' };
import { completeRhythm } from '../support/scene-actions';

test.use({
  selectedPinyinSource: true,
  viewport: { width: 390, height: 844 },
  video: { mode: 'on', size: { width: 390, height: 844 } },
});
async function enter(page: Page, url: string, title: string) {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(url);
  await page.getByRole('button', { name: '在本机生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭' }).click();
  await page.getByRole('button', { name: '进入游戏乐园' }).click();
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/sessions') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: `开始${title}` }).click();
  const session = await (await created).json();
  await expect(page.locator('button[data-option-id]').first()).toBeEnabled({ timeout: 20000 });
  const q = curriculum.exercises.find((q) => q.id === session.tasks[0].exercise.id)!;
  return q.answer.optionId!;
}

test('REDESIGN-05 runner: let every fruit pass, then deliberately collect; never forced to answer', async ({
  page,
  appUrl,
}) => {
  const answer = await enter(page, appUrl, '森林跑酷');
  const stage = page.locator('.adventure-canvas');
  const count = await page.locator('button[data-option-id]').count();
  await expect
    .poll(async () => Number(await stage.getAttribute('data-world-distance')), { timeout: 40000 })
    .toBeGreaterThan(500 + 280 * count);
  expect(await stage.getAttribute('data-world-hit')).toBe('');
  await expect(page.locator('.scene-nav')).toContainText('任务 1 /');
  const untouched = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
  expect(untouched.attempts).toHaveLength(0);
  await stage.screenshot({ path: test.info().outputPath('runner-passes-fruit.png') });
  await page.locator(`button[data-option-id="${answer}"]`).click();
  await expect(page.locator('.scene-nav')).toContainText('任务 2 /', { timeout: 20000 });
});

test('REDESIGN-05 boat: physically hit reef, drag away, hit again and route to chosen dock', async ({
  page,
  appUrl,
}) => {
  const answer = await enter(page, appUrl, '河湾划船');
  const stage = page.locator('.adventure-canvas');
  const box = (await stage.boundingBox())!;
  const at = (x: number, y: number) => ({
    x: box.x + (x / 480) * box.width,
    y: box.y + (y / 400) * box.height,
  });
  const reef = at(150, 220);
  await page.mouse.click(reef.x, reef.y);
  await expect.poll(async () => Number(await stage.getAttribute('data-motor-misses'))).toBe(1);
  const x = Number(await stage.getAttribute('data-world-x'));
  const y = Number(await stage.getAttribute('data-world-y'));
  const boat = at(x, y),
    away = at(65, 340);
  await page.mouse.move(boat.x, boat.y);
  await page.mouse.down();
  await page.mouse.move(away.x, away.y, { steps: 8 });
  await expect
    .poll(async () => Number(await stage.getAttribute('data-world-x')))
    .toBeLessThan(x - 35);
  await page.mouse.up();
  expect(await page.evaluate(() => window.getSelection()?.toString())).toBe('');
  const stopped = await stage.getAttribute('data-world-x');
  await page.waitForTimeout(150);
  expect(await stage.getAttribute('data-world-x')).toBe(stopped);
  await page.mouse.click(reef.x, reef.y);
  await expect.poll(async () => Number(await stage.getAttribute('data-motor-misses'))).toBe(2);
  expect(await stage.getAttribute('data-world-hit')).toBe('');
  await stage.screenshot({ path: test.info().outputPath('boat-reef-contact.png') });
  await page.locator(`button[data-option-id="${answer}"]`).click();
  await expect(page.locator('.scene-nav')).toContainText('任务 2 /', { timeout: 20000 });
  const result = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
  expect(result.attempts).toHaveLength(1);
  expect(result.attempts[0].first_try_correct).toBe(1);
});

test('REDESIGN-05 drum: wrong rhythm can restart without trapping the task or adding learning errors', async ({
  page,
  appUrl,
}) => {
  const answer = await enter(page, appUrl, '节奏鼓岛');
  await page.locator(`button[data-option-id="${answer}"]`).click();
  const score = page.locator('.rhythm-score');
  await expect(score).toBeVisible();
  const first = await score.locator('span').first().innerText();
  const wrong = first === '●' ? '◎ 哒 · 鼓边' : '● 咚 · 鼓心';
  await page.getByRole('button', { name: wrong, exact: true }).click();
  await expect(page.locator('.adventure-canvas')).toHaveAttribute('data-rhythm-index', '0');
  await expect(page.locator('.scene-nav')).toContainText('任务 1 /');
  await completeRhythm(page);
  await expect(page.locator('.scene-nav')).toContainText('任务 2 /', { timeout: 20000 });
  const result = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
  expect(result.attempts).toHaveLength(1);
  expect(result.attempts[0].first_try_correct).toBe(1);
});
