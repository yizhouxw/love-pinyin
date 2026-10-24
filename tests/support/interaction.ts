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
