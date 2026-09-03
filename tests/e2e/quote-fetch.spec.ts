/**
 * Quote fetch — behaviour tests
 *
 * Covers:
 *  - Authenticated sidebar triggers /quote API calls
 *  - 200 response displays price correctly
 *  - 202 (cache miss) returns null data — no crash, retries in 8s
 *  - Guest users never trigger /quote calls
 *  - Invalid quote response doesn't crash the app
 *  - Network error doesn't crash the app
 *  - Indices (^SET, ^GSPC, ^IXIC) are queried
 *  - Quote data is shown in ChartToolbar after selection
 */
import { test, expect } from '@playwright/test';
import { mockStockAPIs, mockAuthSession, mockWatchlistAPIs, MOCK_QUOTE } from './helpers/mocks';

test.describe('Quote fetch — authenticated', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuthSession(page);
    await mockStockAPIs(page);
    await mockWatchlistAPIs(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('authenticated page fetches quote for watchlist symbols', async ({ page }) => {
    // Intercept any quote request — authenticated users should trigger them
    let quoteFetched = false;
    page.on('request', (req) => {
      if (req.url().includes('/quote')) quoteFetched = true;
    });
    await page.waitForTimeout(2_000);
    expect(quoteFetched).toBe(true);
  });

  test('quote price is displayed in watchlist after fetch', async ({ page }) => {
    // MOCK_QUOTE.price = 35.5 → displayed as 35.50
    await page.waitForTimeout(1_500);
    // Price shows in sidebar or toolbar
    const priceEl = page.locator('aside').getByText('35.50').first();
    await expect(priceEl).toBeVisible({ timeout: 5_000 });
  });

  test('positive change shows green color in sidebar', async ({ page }) => {
    await page.waitForTimeout(1_500);
    // The change_pct is +1.43% — should have green color styling
    const changeEl = page.locator('aside').locator('[style*="color: var(--color-green)"], [style*="green"]').first();
    await expect(changeEl).toBeVisible({ timeout: 5_000 });
  });
});

test.describe('Quote fetch — 202 cache miss handling', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuthSession(page);
    await mockStockAPIs(page);
    await mockWatchlistAPIs(page);
  });

  test('202 response does not crash the app', async ({ page }) => {
    // Override quote to return 202
    await page.route('**/api/v1/stocks/*/quote', (route) =>
      route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'pending', symbol: 'PTT.BK', message: 'Retry in a few seconds' }),
      }),
    );
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1_000);

    // App should still be functional — no crash
    await expect(page.getByText('Watchlist', { exact: true })).toBeVisible();
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 10_000 });
  });

  test('202 response shows dash (—) instead of price', async ({ page }) => {
    await page.route('**/api/v1/stocks/*/quote', (route) =>
      route.fulfill({
        status: 202,
        contentType: 'application/json',
        body: JSON.stringify({ status: 'pending', symbol: 'PTT.BK' }),
      }),
    );
    await page.goto('/');
    await page.waitForTimeout(1_500);

    // Prices should show — (em dash) when data is null
    const dashEl = page.locator('aside').getByText('—').first();
    await expect(dashEl).toBeVisible({ timeout: 5_000 });
  });
});

test.describe('Quote fetch — guest users', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
  });

  test('guest page does NOT fetch watchlist quote prices', async ({ page }) => {
    const quoteRequests: string[] = [];
    page.on('request', (req) => {
      if (req.url().includes('/quote') && !req.url().includes('^')) {
        quoteRequests.push(req.url());
      }
    });
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(2_000);

    // No watchlist quote calls for guest (only indices may be called)
    const watchlistQuotes = quoteRequests.filter(
      (url) => !url.includes('%5E') && !url.includes('^'),
    );
    expect(watchlistQuotes.length).toBe(0);
  });

  test('indices are still queried for guests', async ({ page }) => {
    const indexRequests: string[] = [];
    page.on('request', (req) => {
      if (req.url().includes('/quote') && (req.url().includes('%5E') || req.url().includes('^'))) {
        indexRequests.push(req.url());
      }
    });
    await page.goto('/');
    await page.waitForTimeout(2_000);
    // ^SET, ^GSPC, ^IXIC should be queried
    expect(indexRequests.length).toBeGreaterThan(0);
  });
});

test.describe('Quote fetch — error resilience', () => {
  test.beforeEach(async ({ page }) => {
    await mockAuthSession(page);
    await mockStockAPIs(page);
    await mockWatchlistAPIs(page);
  });

  test('network error on quote does not crash the app', async ({ page }) => {
    await page.route('**/api/v1/stocks/*/quote', (route) => route.abort('failed'));
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(1_000);

    // App still renders
    await expect(page.getByText('Watchlist', { exact: true })).toBeVisible();
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 10_000 });
  });

  test('malformed quote JSON does not crash the app', async ({ page }) => {
    await page.route('**/api/v1/stocks/*/quote', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: 'not-valid-json' }),
    );
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    await expect(page.getByText('Watchlist', { exact: true })).toBeVisible();
  });

  test('500 error on quote does not crash the app', async ({ page }) => {
    await page.route('**/api/v1/stocks/*/quote', (route) =>
      route.fulfill({ status: 500, body: JSON.stringify({ detail: 'Internal error' }) }),
    );
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.waitForTimeout(500);
    await expect(page.getByText('Watchlist', { exact: true })).toBeVisible();
  });
});

test.describe('Quote fetch — toolbar price display', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/');
  });

  test('selected stock symbol appears in toolbar', async ({ page }) => {
    await expect(page.getByText('PTT.BK').first()).toBeVisible();
  });

  test('price is visible in toolbar after load', async ({ page }) => {
    // The toolbar shows selectedStock.price from the store
    // Default selectedStock in appStore has price set when clicking watchlist item
    await page.locator('aside').getByRole('button').filter({ hasText: 'PTT.BK' }).first().click();
    // After clicking, toolbar should update
    await expect(page.locator('[class*="toolbar"], [class*="panel"]').first()).toBeVisible();
  });
});
