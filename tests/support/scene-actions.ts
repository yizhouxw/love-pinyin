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
  await option.click();
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
  if (await page.locator('.adventure-canvas[data-scene="drum"]').count()) {
    await expect
      .poll(
        async () =>
          (await page.locator('.rhythm-score').isVisible()) ||
          (await page.getByRole('button', { name: '重试保存这次选择' }).isVisible()) ||
          (await page.locator('.scene-hint').isVisible()),
        { timeout: 15000 },
      )
      .toBe(true);
    if (await page.locator('.rhythm-score').isVisible()) await completeRhythm(page);
  }
}
export async function completeRhythm(page: Page) {
  const beats = await page.locator('.rhythm-score span').allTextContents();
  for (const beat of beats)
    await page
      .getByRole('button', { name: beat === '●' ? '● 咚 · 鼓心' : '◎ 哒 · 鼓边', exact: true })
      .click();
}
