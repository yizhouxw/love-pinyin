import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e-soak',
  outputDir: './test-results/soak',
  workers: 2,
  timeout: 30 * 60_000,
  forbidOnly: !!process.env.CI,
  reporter: [['list']],
  use: {
    actionTimeout: 15_000,
    navigationTimeout: 15_000,
    screenshot: 'only-on-failure',
    trace: 'retain-on-failure',
  },
  projects: [
    { name: 'soak-installed-chrome', use: { ...devices['Desktop Chrome'], channel: 'chrome' } },
    { name: 'soak-webkit', use: { ...devices['Desktop Safari'] } },
  ],
});
