import type { Page } from '@playwright/test';

export async function selectDailyMaterial(page: Page, number: number) {
  const dialog = page.getByRole('dialog', { name: '选择练习' });
  if (!(await dialog.isVisible())) {
    await page.getByRole('button', { name: /^(选择练习，当前|换练习$)/ }).click();
  }
  await dialog.getByRole('button', { name: `第 ${number} 份`, exact: true }).click();
}
