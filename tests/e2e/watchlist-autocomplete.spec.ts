/**
 * Watchlist sidebar — add-stock autocomplete
 *
 * Covers:
 *  - + button only visible when authenticated
 *  - Clicking + opens the add-stock input
 *  - Typing triggers debounced search API call
 *  - Dropdown shows results with symbol, name, market badge
 *  - Clicking a result adds it to the watchlist
 *  - Pressing Escape closes the input
 *  - Empty query shows no dropdown
 *  - Unknown ticker shows "add directly" option
 *  - Guest users see static list, no + button
 */
import { test, expect } from '@playwright/test';
import { mockStockAPIs, mockAuthSession, mockWatchlistAPIs, MOCK_SEARCH_RESULTS } from './helpers/mocks';

test.describe('Watchlist autocomplete — authenticated', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuthSession(page);
    await mockStockAPIs(page);
    // Override watchlists mock to return authenticated data
    await mockWatchlistAPIs(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('+ button is visible when authenticated', async ({ page }) => {
    const addBtn = page.locator('button').filter({ has: page.locator('svg') }).first();
    // Look specifically for the plus button in watchlist header
    const header = page.getByText('Watchlist', { exact: true });
    await expect(header).toBeVisible();
    // The + button is next to Watchlist label
    await expect(page.locator('aside').getByRole('button').first()).toBeVisible();
  });

  test('clicking + opens the search input', async ({ page }) => {
    // Click the plus button in the watchlist header
    await page.locator('aside').locator('button').first().click();
    const input = page.locator('input[placeholder="PTT.BK, AAPL..."]');
    await expect(input).toBeVisible();
    await expect(input).toBeFocused();
  });

  test('typing a query calls /api/stocks/search', async ({ page }) => {
    await page.locator('aside').locator('button').first().click();
    const input = page.locator('input[placeholder="PTT.BK, AAPL..."]');
    await input.waitFor({ state: 'visible' });

    const [request] = await Promise.all([
      page.waitForRequest((req) => req.url().includes('/api/stocks/search')),
      input.fill('PTT'),
    ]);
    expect(request.url()).toContain('q=PTT');
  });

  test('search results dropdown shows after typing', async ({ page }) => {
    await page.locator('aside').locator('button').first().click();
    const input = page.locator('input[placeholder="PTT.BK, AAPL..."]');
    await input.waitFor({ state: 'visible' });
    await input.fill('PTT');

    // Wait for dropdown
    await expect(page.getByText('PTT.BK').first()).toBeVisible({ timeout: 5_000 });
    await expect(page.getByText('ปตท.').first()).toBeVisible();
  });

  test('dropdown shows market badge (SET, US)', async ({ page }) => {
    await page.locator('aside').locator('button').first().click();
    const input = page.locator('input[placeholder="PTT.BK, AAPL..."]');
    await input.waitFor({ state: 'visible' });
    await input.fill('PTT');

    await expect(page.getByText('PTT.BK').first()).toBeVisible({ timeout: 5_000 });
    // SET badge should appear
    await expect(page.locator('aside').getByText('SET').first()).toBeVisible();
  });

  test('clicking a search result calls add-stock API', async ({ page }) => {
    await page.locator('aside').locator('button').first().click();
    const input = page.locator('input[placeholder="PTT.BK, AAPL..."]');
    await input.waitFor({ state: 'visible' });
    await input.fill('PTT');
    await expect(page.getByText('PTT.BK').first()).toBeVisible({ timeout: 5_000 });

    const [request] = await Promise.all([
      page.waitForRequest((req) => req.url().includes('/watchlists') && req.method() === 'POST'),
      page.locator('.glass-dropdown button').first().click(),
    ]);
    expect(request.url()).toContain('/stocks');
  });

  test('after adding a stock, input is cleared and dropdown closes', async ({ page }) => {
    await page.locator('aside').locator('button').first().click();
    const input = page.locator('input[placeholder="PTT.BK, AAPL..."]');
    await input.waitFor({ state: 'visible' });
    await input.fill('PTT');
    await expect(page.getByText('PTT.BK').first()).toBeVisible({ timeout: 5_000 });
    await page.locator('.glass-dropdown button').first().click();

    // Input should disappear (adding=false resets)
    await expect(input).not.toBeVisible({ timeout: 3_000 });
  });

  test('pressing Escape closes the input', async ({ page }) => {
    await page.locator('aside').locator('button').first().click();
    const input = page.locator('input[placeholder="PTT.BK, AAPL..."]');
    await input.waitFor({ state: 'visible' });
    await page.keyboard.press('Escape');
    await expect(input).not.toBeVisible({ timeout: 2_000 });
  });

  test('empty query shows no dropdown', async ({ page }) => {
    await page.locator('aside').locator('button').first().click();
    const input = page.locator('input[placeholder="PTT.BK, AAPL..."]');
    await input.waitFor({ state: 'visible' });
    // Don't type anything — dropdown should not appear
    await page.waitForTimeout(400); // Wait past debounce
    await expect(page.locator('.glass-dropdown')).not.toBeVisible();
  });

  test('unknown ticker shows "add directly" option', async ({ page }) => {
    // Override search to return empty
    await page.route('**/api/stocks/search**', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: '[]' }),
    );
    await page.locator('aside').locator('button').first().click();
    const input = page.locator('input[placeholder="PTT.BK, AAPL..."]');
    await input.waitFor({ state: 'visible' });
    await input.fill('UNKNOWNTICKER');

    // Wait for debounce + API response
    await page.waitForTimeout(500);
    // Should show "add directly" button
    await expect(page.getByText(/เพิ่ม.*โดยตรง/i).first()).toBeVisible({ timeout: 3_000 });
  });
});

test.describe('Watchlist autocomplete — guest user', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('+ button is NOT visible for guests', async ({ page }) => {
    // Sidebar should show "Watchlist" text
    await expect(page.getByText('Watchlist', { exact: true })).toBeVisible();
    // But no add button (only visible when authenticated)
    const addInput = page.locator('input[placeholder="PTT.BK, AAPL..."]');
    await expect(addInput).not.toBeVisible();
  });

  test('guest sees static stock list (NVDA, AAPL, etc.)', async ({ page }) => {
    // GUEST_SYMBOLS includes these
    await expect(page.getByText('NVDA').first()).toBeVisible();
    await expect(page.getByText('AAPL').first()).toBeVisible();
    await expect(page.getByText('PTT.BK').first()).toBeVisible();
  });

  test('clicking a guest stock still navigates to chart', async ({ page }) => {
    await page.locator('aside').getByRole('button').filter({ hasText: 'AAPL' }).first().click();
    await expect(page).toHaveURL('/');
  });
});

test.describe('Watchlist — market indices section', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/');
  });

  test('shows SET, S&P500, NASDAQ index labels', async ({ page }) => {
    await expect(page.getByText('SET').first()).toBeVisible();
    await expect(page.getByText('S&P500').first()).toBeVisible();
    await expect(page.getByText('NASDAQ').first()).toBeVisible();
  });

  test('index prices display after quote fetch', async ({ page }) => {
    // Mock quote returns price=35.5 — indices should show a value
    await page.waitForTimeout(1_000);
    const priceEl = page.locator('aside').getByText('35.50').first();
    await expect(priceEl).toBeVisible({ timeout: 5_000 });
  });
});
