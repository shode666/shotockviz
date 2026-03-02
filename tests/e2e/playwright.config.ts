/**
 * ShotockViz — Root-level Playwright E2E Configuration
 *
 * Separate test project targeting the full Docker stack (Caddy → backend/frontend)
 * at https://localhost (self-signed cert allowed).
 *
 * Run:
 *   cd tests/e2e && npx playwright test           # headless
 *   cd tests/e2e && npx playwright test --ui      # interactive UI
 *   cd tests/e2e && npx playwright test --headed  # headed
 *
 * Requires Docker stack running:
 *   docker compose -f docker-compose.dev.yml up
 */
import { defineConfig, devices } from '@playwright/test';

export default defineConfig({
  testDir: '.',
  testMatch: '**/*.spec.ts',

  /* Per-test timeout */
  timeout: 30_000,

  /* Assertion timeout */
  expect: { timeout: 8_000 },

  /* Retry on CI */
  retries: process.env.CI ? 1 : 0,

  /* Sequential — shared Docker state */
  workers: 1,

  reporter: [
    ['list'],
    ['html', { open: 'never', outputFolder: 'playwright-report' }],
  ],

  use: {
    /* Full-stack Docker/Caddy — HTTPS with self-signed cert */
    baseURL: process.env.BASE_URL ?? 'https://localhost',
    ignoreHTTPSErrors: true,

    /* Capture trace on first retry */
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',

    viewport: { width: 1280, height: 800 },
  },

  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
