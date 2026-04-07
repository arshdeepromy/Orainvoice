import { defineConfig } from '@playwright/test';

export default defineConfig({
  testDir: './tests/e2e/frontend',
  timeout: 30000,
  retries: 0,
  use: {
    headless: true,
    baseURL: process.env.BASE_URL || 'http://localhost:80',
  },
  projects: [
    { name: 'chromium', use: { browserName: 'chromium' } },
  ],
});
