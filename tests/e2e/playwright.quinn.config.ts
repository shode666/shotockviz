/**
 * bd:deps-2026-09 Phase 3b — Quinn's sandbox runner config.
 *
 * Extends the repo's own playwright.config.ts (not modified) with two
 * sandbox-only additions so the suite doesn't hang trying to reach the
 * real internet (this sandbox has no route to accounts.google.com /
 * fonts.googleapis.com — Uma's Phase 3a report used the same block list
 * for the same reason, `outputs/deps-2026-09/13-uma-ui-check.md` §0):
 *
 *   1. baseURL from BASE_URL env (points at the locally-served nitro
 *      build, not the Docker/Caddy https://localhost target).
 *   2. Chromium launch args that black-hole the external hosts at the
 *      browser's own DNS layer + bypass the sandbox's outbound proxy for
 *      them, so failures are instant (connection refused) instead of a
 *      multi-second proxy timeout per request × dozens of requests.
 *
 * NOT a replacement for playwright.config.ts — this file is Quinn's only,
 * for this sandbox run. Full-stack runs use the repo's own config.
 */
import { defineConfig, devices } from '@playwright/test';
import baseConfig from './playwright.config';

const BLOCKED_HOSTS = ['accounts.google.com', 'fonts.googleapis.com', 'fonts.gstatic.com'];

export default defineConfig({
  ...baseConfig,
  use: {
    ...baseConfig.use,
    baseURL: process.env.BASE_URL ?? baseConfig.use?.baseURL,
    ignoreHTTPSErrors: true,
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        launchOptions: {
          args: [
            '--proxy-server=direct://',
            '--proxy-bypass-list=*',
            `--host-resolver-rules=${BLOCKED_HOSTS.map((h) => `MAP ${h} 127.0.0.1`).join(', ')}`,
          ],
        },
      },
    },
  ],
});
