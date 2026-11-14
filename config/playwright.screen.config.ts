import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: '../tests',
  testMatch: [
    /e2e-live\/.*\.spec\.ts/,
    /e2e-product\/(touch-playgrounds|experience-acceptance|game-start|pinyin-shop|lesson-activities|writing-playback)\.spec\.ts/,
  ],
  // SHOP-05 is a desktop keyboard/synthetic-microphone contract suite.
  // Phone shop flows use SHOP-10/17/22 and the real-server permission tests.
  grepInvert: /SHOP-05/,
  outputDir: '../test-results/screens',
  workers: 2,
  timeout: 120_000,
  reporter: [['list']],
  use: { trace: 'retain-on-failure', screenshot: 'only-on-failure' },
  projects: [
    { name: 'screen-phone-chromium', use: { ...devices['Pixel 5'] } },
    { name: 'screen-phone-webkit', use: { ...devices['iPhone 13'] } },
  ],
});
