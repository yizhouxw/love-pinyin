import { expect, type Page } from '@playwright/test';
/** Real controls only. Read the visible route geometry, never mutate game state or submit an answer. */
export async function playScene(
  page: Page,
  optionId: string,
  { continuous = false }: { continuous?: boolean } = {},
) {
  const stage = page.getByRole('group', { name: '游戏操作区：方向键控制，空格行动' });
  await expect(stage).toBeVisible();
  const auto = page.getByRole('button', { name: /连续旅程：/ });
  if (!continuous && (await auto.getAttribute('aria-pressed')) === 'true') await auto.click();
  await page.getByRole('button', { name: '听拼音', exact: true }).click();
  const actions = page.getByRole('group', { name: '场景动作' }).getByRole('button');
  await expect(actions.nth(1)).toBeEnabled({ timeout: 20000 });
  const scene = await stage.getAttribute('data-scene');
  const goal = Number(await stage.getAttribute('data-choice-at'));
  let index = -1;
  const targets = stage.locator('[data-scene-target]');
  if (scene !== 'space')
    index = (
      await targets.evaluateAll((nodes) => nodes.map((n) => n.getAttribute('data-scene-target')))
    ).indexOf(optionId);
  // Space planets enter view only after the meteor route. Index is resolved below.
  if (scene === 'runner') {
    expect(index).toBeGreaterThanOrEqual(0);
    for (let step = 0; step < 180; step++) {
      const snapshot = await stage.evaluate((el) => ({
        distance: Number(el.getAttribute('data-world-distance')),
        x: Number(el.getAttribute('data-world-x')),
        jump: Number(el.getAttribute('data-world-jump')),
        obstacles: Array.from(el.querySelectorAll('[data-obstacle]')).map((o) => ({
          at: Number(o.getAttribute('data-obstacle-at')),
          lane: Number(o.getAttribute('data-obstacle-lane')),
          kind: o.getAttribute('data-obstacle-kind'),
        })),
        count: el.querySelectorAll('[data-scene-target]').length,
      }));
      if (snapshot.distance >= goal) break;
      const obstacle = snapshot.obstacles.find(
        (o) => o.at > snapshot.distance && o.at - snapshot.distance < 55,
      );
      if (obstacle) {
        const ox = 120 + ((obstacle.lane % snapshot.count) * 560) / Math.max(1, snapshot.count - 1);
        if (
          obstacle.kind === 'root' &&
          (obstacle.lane === -1 || Math.abs(ox - snapshot.x) < 65) &&
          snapshot.jump < 1
        )
          await page.keyboard.press('Space');
        if (obstacle.kind === 'bush' && Math.abs(ox - snapshot.x) < 80)
          await page.keyboard.press(snapshot.x < 500 ? 'ArrowRight' : 'ArrowLeft');
      } else if (!snapshot.obstacles.some((o) => o.at > snapshot.distance)) {
        const x = 120 + (index * 560) / Math.max(1, snapshot.count - 1);
        if (Math.abs(snapshot.x - x) > 20)
          await page.keyboard.press(snapshot.x < x ? 'ArrowRight' : 'ArrowLeft');
      }
      await page.waitForTimeout(100);
      if (await stage.getAttribute('data-world-hit')) break;
    }
  } else if (scene === 'drum') {
    expect(index).toBeGreaterThanOrEqual(0);
    for (let i = 0; i < index; i++) await page.keyboard.press('ArrowRight');
    await expect
      .poll(
        async () => Math.abs(Number(await targets.nth(index).getAttribute('data-target-x')) - 180),
        { timeout: 30000 },
      )
      .toBeLessThan(4);
    await page.keyboard.press('Space');
  } else if (scene === 'boat') {
    expect(index).toBeGreaterThanOrEqual(0);
    const count = await targets.count();
    for (let step = 0; step < 350; step++) {
      const snapshot = await stage.evaluate((el) => ({
        distance: Number(el.getAttribute('data-world-distance')),
        x: Number(el.getAttribute('data-world-x')),
        vx: Number(el.getAttribute('data-world-vx')),
        obstacles: Array.from(el.querySelectorAll('[data-obstacle]')).map((o) => ({
          at: Number(o.getAttribute('data-obstacle-at')),
          lane: Number(o.getAttribute('data-obstacle-lane')),
        })),
      }));
      const next = snapshot.obstacles.find(
        (o) => o.at > snapshot.distance && o.at - snapshot.distance < 100,
      );
      const targetX = next
        ? 120 + (((next.lane + 1) % count) * 560) / Math.max(1, count - 1)
        : 120 + (index * 560) / Math.max(1, count - 1);
      const projected = snapshot.x + snapshot.vx * 0.35;
      if (Math.abs(targetX - projected) > 35)
        await page.keyboard.press(targetX < projected ? 'ArrowLeft' : 'ArrowRight');
      await page.keyboard.press('Space');
      await page.waitForTimeout(120);
      if (await stage.getAttribute('data-world-hit')) break;
    }
  } else {
    // Stay away from the first meteor lane, then aim at actual planets after the flight.
    for (let n = 0; n < 350; n++) {
      const snapshot = await stage.evaluate((el) => ({
        distance: Number(el.getAttribute('data-world-distance')),
        x: Number(el.getAttribute('data-world-x')),
        obstacles: Array.from(el.querySelectorAll('[data-obstacle]')).map((o) => ({
          at: Number(o.getAttribute('data-obstacle-at')),
          lane: Number(o.getAttribute('data-obstacle-lane')),
        })),
      }));
      if (snapshot.distance >= goal) break;
      const count = Number(await stage.getAttribute('data-option-count'));
      const obstacle = snapshot.obstacles.find(
        (o) => o.at > snapshot.distance && o.at - snapshot.distance < 150,
      );
      if (
        obstacle &&
        Math.abs(120 + ((obstacle.lane % count) * 560) / Math.max(1, count - 1) - snapshot.x) < 80
      )
        await page.keyboard.press(snapshot.x < 500 ? 'ArrowRight' : 'ArrowLeft');
      await page.waitForTimeout(100);
    }
    await expect
      .poll(async () => Number(await stage.getAttribute('data-world-distance')), { timeout: 5000 })
      .toBeGreaterThanOrEqual(goal);
    await expect(targets.first()).toBeVisible();
    index = (
      await targets.evaluateAll((nodes) => nodes.map((n) => n.getAttribute('data-scene-target')))
    ).indexOf(optionId);
    expect(index).toBeGreaterThanOrEqual(0);
    const x = Number(await targets.nth(index).getAttribute('data-target-x'));
    for (let n = 0; n < 30; n++) {
      const current = Number(await stage.getAttribute('data-world-x'));
      if (Math.abs(x - current) < 15) break;
      await page.keyboard.press(x < current ? 'ArrowLeft' : 'ArrowRight');
    }
    await page.keyboard.press('Space');
  }
  await expect(stage).toHaveAttribute('data-world-hit', String(index), { timeout: 20000 });
}
