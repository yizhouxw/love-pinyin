import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  outputDir: './test-results/product',
  testDir: './tests/e2e-product',
  workers: 1,
  timeout: 120_000,
  forbidOnly: !!process.env.CI,
  reporter: [['list']],
  use: { trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [
    { name: 'product-desktop-chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'product-desktop-webkit', use: { ...devices['Desktop Safari'] } },
  ],
});
