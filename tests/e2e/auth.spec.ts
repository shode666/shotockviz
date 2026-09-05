/**
 * Authentication page tests
 */
import { test, expect } from '@playwright/test';
import { mockStockAPIs, mockAuthSession, MOCK_AUTH_ME } from './helpers/mocks';

test.describe('Login Page', () => {
  test.beforeEach(async ({ page }) => {
    // Ensure no auth token is present
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
  });

  test('renders the login page at /login', async ({ page }) => {
    await page.goto('/login');
    await expect(page).toHaveURL(/\/login/);
  });

  test('shows app name "Stock Analysis Platform"', async ({ page }) => {
    await page.goto('/login');
    await expect(page.getByText('Stock Analysis Platform')).toBeVisible();
  });

  test('shows "ShotockViz" branding text', async ({ page }) => {
    await page.goto('/login');
    // The logo text has "S", "ho", "tock", "Viz" in separate spans
    await expect(page.getByText('Viz').first()).toBeVisible();
  });

  test('shows the Google Sign-in button container', async ({ page }) => {
    await page.goto('/login');
    // GoogleLogin renders an iframe from accounts.google.com
    // We check the container div exists — LoginPage.tsx:164 renders
    // class="flex items-center justify-center" (attribute-substring selector
    // '[class*="flex justify-center"]' never matched: "items-center" sits
    // between the two words in the real class string).
    const googleContainer = page.locator('div.flex.items-center.justify-center').last();
    await expect(googleContainer).toBeVisible();
  });

  test('shows descriptive subtitle text', async ({ page }) => {
    await page.goto('/login');
    // Thai subtitle text
    await expect(page.getByText(/Self-hosted/)).toBeVisible();
  });
});

test.describe('Authenticated state', () => {
  test('shows user avatar button when logged in', async ({ page }) => {
    await mockStockAPIs(page);
    await mockAuthSession(page, MOCK_AUTH_ME);
    await page.goto('/');

    // After mount, checkAuth() is called → GET /api/v1/auth/me → sets user
    // The avatar button shows first letter of display_name ('Test User' → 'T').
    // Scoped to <nav> + exact match — unscoped substring 'T' strict-mode-violates
    // against 13 elements (watchlist rows, chart-type/S-R buttons, etc).
    await expect(
      page.locator('nav').getByRole('button', { name: 'T', exact: true })
    ).toBeVisible({ timeout: 5000 });
  });

  test('shows Login link when not authenticated', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/');

    await expect(page.getByRole('link', { name: 'Login' })).toBeVisible();
  });
});
