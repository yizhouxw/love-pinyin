import { expect, type Page } from '@playwright/test';
/** Use the same tap alternatives and visible rhythm score offered to children. */
export async function playScene(page: Page, optionId: string) {
  const stage = page.locator('.adventure-canvas');
  await expect(stage).toBeVisible();
  const start = page.getByRole('button', { name: '▶ 开始游戏', exact: true });
  if (await start.isVisible()) await start.click();
  await page.getByRole('button', { name: '听拼音', exact: true }).click();
  const option = page.locator(`button[data-option-id="${optionId}"]`);
  await expect(option).toBeEnabled({ timeout: 20000 });
  const task = await page.locator('.scene-nav').innerText();
  const scene = await stage.getAttribute('data-scene');
  if (scene === 'drum') {
    const index = await page
      .locator('.adventure-drum-picks button')
      .evaluateAll(
        (buttons, id) => buttons.findIndex((b) => b.getAttribute('data-option-id') === id),
        optionId,
      );
    await expect
      .poll(
        async () => {
          const y = await stage.locator('svg text').nth(index).getAttribute('y');
          return Math.abs(Number(y) - 8 - 310);
        },
        { intervals: [30], timeout: 12000 },
      )
      .toBeLessThan(25);
  }
  await option.click();
  if (scene === 'space')
    await page.getByRole('button', { name: '发射 · 空格', exact: true }).click();
  await expect
    .poll(
      () =>
        page.evaluate((previousTask) => {
          const canvas = document.querySelector('.adventure-canvas');
          const nav = document.querySelector<HTMLElement>('.scene-nav');
          return (
            !canvas ||
            canvas.getAttribute('data-world-hit') !== '' ||
            nav?.innerText !== previousTask
          );
        }, task),
      { timeout: 20000 },
    )
    .toBe(true);
}
