import { expect, type Page } from '@playwright/test';
/** Drive actual keyboard/touch controls; inspect visible world geometry, never inject answers. */
export async function playScene(page: Page, optionId: string) {
  const stage = page.getByRole('group', { name: '游戏操作区：方向键控制，空格行动' });
  await expect(stage).toBeVisible();
  // Explicit standard audio also works after page reload (gesture required).
  await page.getByRole('button', { name: '听拼音', exact: true }).click();
  const actions = page.getByRole('group', { name: '场景动作' }).getByRole('button');
  await expect(actions.nth(1)).toBeEnabled();
  const scene = await stage.getAttribute('data-scene');
  const targets = stage.locator('[data-scene-target]');
  const ids = await targets.evaluateAll((nodes) =>
    nodes.map((n) => n.getAttribute('data-scene-target')),
  );
  const index = ids.indexOf(optionId);
  expect(index).toBeGreaterThanOrEqual(0);
  await stage.focus();
  if (scene === 'runner') {
    const current = Math.floor(ids.length / 2);
    for (let i = 0; i < Math.abs(index - current); i++)
      await stage.press(index < current ? 'ArrowLeft' : 'ArrowRight');
    await expect
      .poll(async () => Number(await stage.getAttribute('data-world-distance')))
      .toBeGreaterThanOrEqual(145);
    await stage.press('Space');
  } else if (scene === 'drum') {
    for (let i = 0; i < index; i++) await stage.press('ArrowRight');
    await expect
      .poll(
        async () => Math.abs(Number(await targets.nth(index).getAttribute('data-target-x')) - 180),
        { timeout: 20000 },
      )
      .toBeLessThan(3);
    await stage.press('Space');
  } else if (scene === 'boat') {
    const target = Number(await targets.nth(index).getAttribute('data-target-x'));
    let x = Number(await stage.getAttribute('data-world-x'));
    // Steer through real inertia, then row ahead when aligned.
    for (let tries = 0; Math.abs(target - x) > 35 && tries < 20; tries++) {
      await stage.press(target < x ? 'ArrowLeft' : 'ArrowRight');
      await page.waitForTimeout(300);
      x = Number(await stage.getAttribute('data-world-x'));
    }
    for (let i = 0; i < 14 && !(await stage.getAttribute('data-world-hit')); i++) {
      await stage.press('Space');
      await page.waitForTimeout(50);
    }
  } else {
    const target = Number(await targets.nth(index).getAttribute('data-target-x'));
    let x = Number(await stage.getAttribute('data-world-x'));
    for (let tries = 0; Math.abs(target - x) > 15 && tries < 30; tries++) {
      await stage.press(target < x ? 'ArrowLeft' : 'ArrowRight');
      x = Number(await stage.getAttribute('data-world-x'));
    }
    await stage.press('Space');
  }
  await expect(stage).toHaveAttribute('data-world-hit', String(index), { timeout: 20000 });
}
