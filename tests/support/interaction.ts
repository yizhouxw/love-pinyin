import type { Page } from '@playwright/test';

/** Use the same visible disclosure controls as a family, without exposing unrelated settings. */
export async function openSection(page: Page, name: string, optional = false) {
  const summary = page
    .locator('summary')
    .filter({ hasText: new RegExp(`^${name}$`) })
    .first();
  if (optional && !(await summary.count())) return;
  await summary.waitFor({ state: 'visible' });
  if (!(await summary.evaluate((element) => (element.parentElement as HTMLDetailsElement).open)))
    await summary.click();
}

/** Home game settings are intentionally collapsed until the family asks to adjust them. */
export async function openGameSettings(page: Page, title: string) {
  const summary = page.getByLabel(`${title}设置`, { exact: true });
  await summary.waitFor({ state: 'visible' });
  if (!(await summary.evaluate((element) => (element.parentElement as HTMLDetailsElement).open)))
    await summary.click();
}
