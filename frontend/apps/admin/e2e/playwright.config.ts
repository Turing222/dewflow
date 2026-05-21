import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests',
  fullyParallel: true,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: process.env.CI ? 1 : undefined,
  reporter: process.env.CI ? 'github' : 'html',
  timeout: 30000,
  expect: { timeout: 10000 },
  use: {
    baseURL: process.env.E2E_BASE_URL || 'http://localhost:5173',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
  },
  projects: [
    {
      name: 'mock',
      testDir: './tests/mock',
    },
    {
      name: 'smoke',
      testDir: './tests/smoke',
    },
  ],
  webServer: {
    command: 'pnpm --filter admin dev',
    port: 5173,
    reuseExistingServer: !process.env.CI,
    timeout: 30000,
  },
});
