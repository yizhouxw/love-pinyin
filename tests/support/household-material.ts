import { expect, type Page } from '@playwright/test';

export async function pairForHouseholdMaterial(page: Page, url: string) {
  await page.goto(url);
  await page.getByRole('button', { name: '在本机生成家长配对码' }).click();
  const code = (await page.locator('.pair-code').innerText()).match(/[A-Z2-9]{8}/)![0];
  await page.getByLabel('家长配对码').fill(code);
  await page.getByRole('button', { name: '连接家庭' }).click();
  await expect(page.getByRole('button', { name: '家长管理', exact: true })).toBeVisible();
}

export async function useHouseholdMaterial(page: Page) {
  await page.getByRole('button', { name: '家长管理', exact: true }).click();
  await page.getByRole('button', { name: '我是家长，继续' }).click();
  await page.getByText('高级设置', { exact: true }).click();
  await Promise.all([
    page.waitForEvent('load'),
    page.getByRole('combobox', { name: '学习素材', exact: true }).selectOption('household'),
  ]);
}
