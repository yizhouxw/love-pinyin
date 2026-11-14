import { expect } from '@playwright/test';
import { test } from '../support/real-server';
import catalog from '../../content/games.json' with { type: 'json' };
import curriculum from '../../content/curriculum.json' with { type: 'json' };
import { playScene } from '../support/scene-actions';

test.use({ selectedPinyinSource: true, viewport: { width: 390, height: 844 } });
for (const game of catalog.games) {
  test(`REDESIGN-07 ${game.scene}: explicit start, legacy motion preference ignored, playable after reload`, async ({
    page,
    appUrl,
  }) => {
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.goto(appUrl);
    await page.getByRole('button', { name: '在本机生成家长配对码' }).click();
    await page.getByRole('button', { name: '连接家庭' }).click();
    await expect(page.getByRole('button', { name: '进入游戏乐园' })).toBeVisible();
    const csrf = (await page.context().cookies()).find((c) => c.name === 'lp_csrf')!.value;
    const legacy = await page.request.put(`${appUrl}/api/v1/household/settings`, {
      headers: { 'X-LP-CSRF': csrf, Origin: appUrl },
      data: { soundEnabled: true, reducedMotion: true },
    });
    expect(legacy.ok()).toBe(true);
    expect((await legacy.json()).settings.reducedMotion).toBe(false);
    await page.getByRole('button', { name: '进入游戏乐园' }).click();
    const created = page.waitForResponse(
      (r) => r.url().endsWith('/sessions') && r.request().method() === 'POST',
    );
    await page.getByRole('button', { name: `开始${game.title}` }).click();
    const session = await (await created).json();
    const stage = page.locator('.adventure-canvas');
    const start = page.getByRole('button', { name: '▶ 开始游戏', exact: true });
    await expect(start).toBeVisible();
    await expect(page.locator('button[data-option-id]').first()).toBeDisabled();
    const before = await stage.locator('svg').innerHTML();
    await stage.focus();
    const initialScroll = await page.evaluate(() => scrollY);
    await page.keyboard.press('ArrowUp');
    await page.keyboard.press('Space');
    await page.waitForTimeout(350);
    expect(await stage.locator('svg').innerHTML()).toBe(before);
    if (game.scene === 'runner') expect(await page.evaluate(() => scrollY)).toBe(initialScroll);
    await start.click();
    await expect(start).toBeHidden();
    const answer = curriculum.exercises.find((q) => q.id === session.tasks[0].exercise.id)!.answer
      .optionId!;
    await playScene(page, answer);
    await expect(page.locator('.scene-nav')).toContainText('任务 2 /', { timeout: 20000 });
    await expect(start).toBeHidden();
    await page.reload();
    await expect(start).toBeVisible();
    await expect(page.locator('button[data-option-id]').first()).toBeDisabled();
    await start.click();
    await expect(page.locator('button[data-option-id]').first()).toBeEnabled({ timeout: 20000 });
    if (game.scene === 'runner') {
      const distance = Number(await stage.getAttribute('data-world-distance'));
      await expect
        .poll(async () => Number(await stage.getAttribute('data-world-distance')))
        .toBeGreaterThan(distance + 10);
      for (const key of ['Space', 'ArrowUp']) {
        await expect.poll(async () => Number(await stage.getAttribute('data-world-y'))).toBe(330);
        await page.evaluate(() => (document.activeElement as HTMLElement)?.blur());
        await page.keyboard.press(key);
        await expect
          .poll(async () => Number(await stage.getAttribute('data-world-y')))
          .toBeLessThan(300);
      }
      await expect.poll(async () => Number(await stage.getAttribute('data-world-y'))).toBe(330);
      await page.getByRole('button', { name: '跳起来 ↑', exact: true }).click();
      await expect
        .poll(async () => Number(await stage.getAttribute('data-world-y')))
        .toBeLessThan(300);
      await page.getByRole('button', { name: 'Ⅱ 暂停', exact: true }).click();
      const y = await stage.getAttribute('data-world-y');
      await stage.focus();
      await page.keyboard.press('Space');
      await page.keyboard.press('ArrowUp');
      await page.waitForTimeout(250);
      expect(await stage.getAttribute('data-world-y')).toBe(y);
    }
  });
}
