import type { Page } from '@playwright/test';

/** Authored array positions are not screen positions; all choices keep their stable ID. */
export function optionById(page: Page, optionId: string | undefined) {
  if (!optionId) throw new Error('Expected an objective option ID');
  return page.locator(`.game-option[data-option-id=${JSON.stringify(optionId)}]`);
}
