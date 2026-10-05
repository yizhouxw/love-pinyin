import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  outputDir: './test-results/live',
  testDir: './tests/e2e-live',
  workers: 1,
  timeout: 60_000,
  forbidOnly: !!process.env.CI,
  reporter: [['list']],
  use: { trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [
    { name: 'live-desktop-chromium', use: { ...devices['Desktop Chrome'] } },
    { name: 'live-desktop-webkit', use: { ...devices['Desktop Safari'] } },
  ],
});
