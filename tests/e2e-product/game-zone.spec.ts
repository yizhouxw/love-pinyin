import { execFileSync } from 'node:child_process';
import { expect, type Page } from '@playwright/test';
import curriculum from '../../content/curriculum.json' with { type: 'json' };
import { test } from '../support/real-server';
import { openSection } from '../support/interaction';
import { optionById } from '../support/options';

test.use({ selectedPinyinSource: true });

async function pair(page: Page, url: string) {
  await page.goto(url);
  await page.getByRole('button', { name: '在 Mac 上生成家长配对码' }).click();
  await page.getByRole('button', { name: '连接家庭' }).click();
  await expect(page.getByRole('button', { name: '进入游戏乐园' })).toBeVisible();
}
async function parent(page: Page) {
  await page.getByRole('button', { name: '家长管理', exact: true }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
}
function python(directory: string, source: string) {
  execFileSync('uv', ['run', '--locked', 'python', '-c', source], {
    env: { ...process.env, LOVE_PINYIN_DATA_DIR: directory },
  });
}

test('GAME-01/03: spoken game, first-answer evidence, corrections, skips and frozen reload', async ({
  page,
  appUrl,
}) => {
  const voices: string[] = [];
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  page.on('request', (request) => {
    if (request.url().includes('/voice/')) voices.push(request.url());
  });
  await pair(page, appUrl);
  await parent(page);
  await page.getByRole('combobox').selectOption('lesson-03');
  await page.getByRole('button', { name: '保存', exact: true }).click();
  await page.getByRole('button', { name: '返回学习', exact: true }).click();
  await page.getByRole('button', { name: '进入游戏乐园' }).click();
  await expect(page.getByLabel('游戏时长约定')).toContainText('每次最多 15 分钟');
  await expect(page.getByLabel('游戏时长约定')).toContainText('每天最多 60 分钟');
  await expect(page.getByRole('button', { name: '开始拼读列车' })).toBeEnabled();
  for (const width of [1280, 390, 320]) {
    await page.setViewportSize({ width, height: 900 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(
      true,
    );
    await page.screenshot({
      path: test.info().outputPath(`game-zone-${width}.png`),
      fullPage: true,
    });
  }
  await page.getByRole('button', { name: '听玩法：字形侦探', exact: true }).click();
  await expect.poll(() => voices.some((url) => url.endsWith('/voice/ui-game_shape'))).toBe(true);
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/sessions') && r.request().method() === 'POST',
  );
  await expect(page.getByRole('button', { name: '开始字形侦探' })).toBeEnabled();
  await page.getByRole('button', { name: '开始字形侦探' }).press('Enter');
  const session = await (await created).json();
  const first = session.tasks[0];
  const question = curriculum.exercises.find((q) => q.id === first.exercise.id)!;
  const wrong = question.options.find((o) => o.id !== question.answer.optionId)!;
  await expect(page.getByLabel('本关探索进度')).toBeVisible();
  await expect(optionById(page, wrong.id)).toBeEnabled();
  await optionById(page, wrong.id).press('Enter');
  await expect(page.locator('.feedback')).toContainText('没关系');
  await expect(optionById(page, question.answer.optionId!)).toBeEnabled();
  await optionById(page, question.answer.optionId!).press('Enter');
  await expect(page.locator('.feedback')).toContainText('找到正确答案');
  await page.getByRole('button', { name: '继续 →', exact: true }).click();
  await page.reload();
  await expect(page.locator('.play-nav strong')).toHaveText(`第 2 / ${session.tasks.length} 关`);
  const restored = await (await page.request.get(`${appUrl}/api/v1/sessions/current`)).json();
  expect(restored.tasks).toEqual(session.tasks);
  expect(restored.gameId).toBe('shape');
  for (let i = 1; i < session.tasks.length; i++) {
    await page.getByRole('button', { name: '先跳过这题' }).click();
  }
  await expect(page.getByLabel('本次练习小结')).toContainText('首次待巩固：1 题');
  await page.getByRole('button', { name: '回到游戏乐园', exact: true }).click();
  await expect(page.getByLabel('游戏学习效果')).toContainText('1 次作答');
  const data = await (await page.request.get(`${appUrl}/api/v1/games`)).json();
  expect(data.report.answered).toBe(1);
  expect(data.report.independentCorrect).toBe(0);
  expect(data.report.skipped).toBe(session.tasks.length - 1);
  expect(data.report.practiceKnowledgeIds.length).toBeGreaterThan(0);
  const exported = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
  expect(exported.attempts).toHaveLength(1);
  expect(exported.attempts[0].first_try_correct).toBe(0);
  await page.getByRole('button', { name: '回到学习' }).click();
  await parent(page);
  await openSection(page, '游戏时长与学习效果');
  await expect(page.getByLabel('游戏学习效果')).toContainText('1 次作答');
  await page.screenshot({ path: test.info().outputPath('game-parent-320.png'), fullPage: true });
  expect(errors).toEqual([]);
});

test('GAME-02: real parent settings, expiry, reload, offline pause and server restart', async ({
  page,
  appUrl,
  dataDirectory,
  serverControl,
}) => {
  await pair(page, appUrl);
  await parent(page);
  await openSection(page, '游戏时长与学习效果');
  await page.getByLabel('每次游戏最多分钟').fill('1');
  await page.getByLabel('每天游戏最多分钟').fill('2');
  await page.getByRole('button', { name: '保存游戏时长' }).click();
  await expect(page.getByRole('status').filter({ hasText: '游戏时长已保存' })).toBeVisible();
  await page.getByRole('button', { name: '返回学习', exact: true }).click();
  await page.getByRole('button', { name: '进入游戏乐园' }).click();
  await page.getByRole('button', { name: '开始字形侦探' }).click();
  await expect(page.locator('.game-option').first()).toBeEnabled();
  await page.route('**/api/v1/games/heartbeat', (route) => route.abort('failed'));
  await expect(page.getByRole('heading', { name: '游戏先暂停一下' })).toBeVisible({
    timeout: 15000,
  });
  expect(await page.locator('.game-option').count()).toBe(0);
  await page.unroute('**/api/v1/games/heartbeat');
  await page.getByRole('button', { name: '继续游戏', exact: true }).click();
  await expect(page.locator('.game-option').first()).toBeEnabled();
  // Fast-forward only the disposable database's clock usage. The production API,
  // browser timer and media remain real; this is not a 15-minute duration claim.
  python(
    dataDirectory,
    `
import json
from server import storage
with storage.transaction() as db:
    row = db.execute('SELECT id,game_state_json FROM household').fetchone()
    state = json.loads(row['game_state_json'])
    state['runSeconds'] = 59
    db.execute('UPDATE household SET game_state_json=? WHERE id=?', (json.dumps(state),row['id']))
`,
  );
  await expect(page.getByRole('heading', { name: '该休息一下啦' })).toBeVisible({ timeout: 20000 });
  await expect(page.getByLabel('游戏已暂停')).toContainText('连续休息 10 分钟');
  expect(await page.locator('.game-option').count()).toBe(0);
  await page.screenshot({ path: test.info().outputPath('game-rest.png'), fullPage: true });
  await page.reload();
  await expect(page.getByRole('heading', { name: '该休息一下啦' })).toBeVisible();
  await serverControl.stop();
  await serverControl.start();
  await page.getByRole('button', { name: '休息后检查时间' }).click();
  await expect(page.getByRole('heading', { name: '该休息一下啦' })).toBeVisible();
  await page.getByRole('button', { name: '保存并回游戏乐园' }).click();
  await expect(page.getByRole('button', { name: '开始字形侦探' })).toBeDisabled();
  // A later day restores the daily budget; only a real ten-minute idle gap
  // resets a run. Represent that gap in the isolated server state.
  python(
    dataDirectory,
    `
import json
from server import storage
with storage.transaction() as db:
    row = db.execute('SELECT id,game_state_json FROM household').fetchone()
    state = json.loads(row['game_state_json'])
    state['leaseUntil'] = storage.now_utc().timestamp()-601
    state['accountedAt'] = state['leaseUntil']
    db.execute('UPDATE household SET game_state_json=? WHERE id=?',(json.dumps(state),row['id']))
`,
  );
  await page.getByRole('button', { name: '刷新可玩时间' }).click();
  await expect(page.getByRole('button', { name: '开始字形侦探' })).toBeEnabled();
});

test('GAME-01: real standard sound completes before choosing treasure; blend is reversible', async ({
  page,
  appUrl,
}) => {
  await pair(page, appUrl);
  await parent(page);
  await page.getByRole('combobox').selectOption('lesson-03');
  await page.getByRole('button', { name: '保存', exact: true }).click();
  await page.getByRole('button', { name: '返回学习', exact: true }).click();
  await page.getByRole('button', { name: '进入游戏乐园' }).click();
  await page.getByRole('button', { name: '开始听音寻宝' }).click();
  await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 25000 });
  await page.getByRole('button', { name: '退出练习' }).click();
  const created = page.waitForResponse(
    (r) => r.url().endsWith('/sessions') && r.request().method() === 'POST',
  );
  await page.getByRole('button', { name: '开始拼读列车' }).click();
  const session = await (await created).json();
  await expect(page.locator('.game-option').first()).toBeEnabled({ timeout: 25000 });
  await page.locator('.game-option').first().press('Enter');
  await expect(page.getByRole('button', { name: '确认拼读', exact: true })).toBeFocused();
  await page.getByRole('button', { name: '撤销拼读选择', exact: true }).press('Enter');
  await expect(page.getByLabel('当前拼读预览')).toHaveCount(0);
  const backup = await (await page.request.get(`${appUrl}/api/v1/profiles/export`)).json();
  expect(backup.attempts).toHaveLength(0);
  expect(
    session.tasks.every((t: { exercise: { type: string } }) => t.exercise.type === 'blend-choice'),
  ).toBe(true);
});
