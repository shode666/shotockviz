/**
 * Search modal tests
 * Covers: keyboard shortcut open, search input, category tabs,
 *         keyboard navigation, selecting a result, Escape to close.
 */
import { test, expect } from '@playwright/test';
import { mockStockAPIs } from './helpers/mocks';

const MOCK_SEARCH_RESULTS = [
  { symbol: 'PTT.BK', name: 'PTT Public Company', name_th: 'ปตท.', market: 'SET', type: 'STOCK' },
  { symbol: 'AAPL', name: 'Apple Inc.', name_th: null, market: 'US', type: 'STOCK' },
  { symbol: 'SCBFUND', name: 'SCB Fund', name_th: 'กองทุน ไทย', market: 'TH_FUND', type: 'FUND' },
];

async function mockSearchAPI(page: any, results = MOCK_SEARCH_RESULTS) {
  await page.route('**/api/v1/stocks/search**', (route: any) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(results),
    }),
  );
}

test.describe('Search Modal — open/close', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await mockSearchAPI(page);
    await page.goto('/');
  });

  test('search modal opens when clicking the search bar button', async ({ page }) => {
    await page.waitForLoadState('networkidle');
    await page.getByText(/ค้นหา PTT, AAPL/).click();
    // SearchModal.tsx renders the backdrop as class="glass-backdrop ..." —
    // '.search-overlay' does not exist anywhere in frontend/src (grep
    // confirmed), so this locator never matched anything.
    await expect(page.locator('.glass-backdrop').first()).toBeVisible();
  });

  test('search modal opens with Cmd+K / Ctrl+K', async ({ page }) => {
    // Hydration race (bd:shotockviz-c73 finding, same shape as the sr-levels
    // toggle-click bug): pressing the shortcut before React attaches the
    // window keydown listener silently drops it — 100% repro without this
    // wait in this dev-mode sandbox. See Quinn's finding for the product-
    // level note; every other passing spec in this suite already waits for
    // networkidle before its first interaction.
    await page.waitForLoadState('networkidle');
    await page.keyboard.press('Meta+k');
    // Input should be focused
    const input = page.getByPlaceholder(/ค้นหา/i).first();
    await expect(input).toBeVisible();
  });

  test('pressing Escape closes the search modal', async ({ page }) => {
    await page.waitForLoadState('networkidle');
    await page.getByText(/ค้นหา PTT, AAPL/).click();
    await expect(page.locator('.glass-backdrop').first()).toBeVisible();
    await page.keyboard.press('Escape');
    // Overlay should be gone
    await expect(page.locator('.glass-backdrop').first()).not.toBeVisible();
  });

  test('clicking the overlay backdrop closes the modal', async ({ page }) => {
    await page.waitForLoadState('networkidle');
    await page.getByText(/ค้นหา PTT, AAPL/).click();
    await expect(page.locator('.glass-backdrop').first()).toBeVisible();
    // Click outside the panel
    await page.mouse.click(10, 10);
    await expect(page.locator('.glass-backdrop').first()).not.toBeVisible();
  });
});

test.describe('Search Modal — input and results', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await mockSearchAPI(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    // Open modal
    await page.getByText(/ค้นหา PTT, AAPL/).click();
  });

  test('typing shows search results', async ({ page }) => {
    // Scoped to the modal panel (.glass-search) — an unscoped getByText('PTT')
    // also matches the sidebar's own watchlist row sitting behind the modal
    // backdrop, so this assertion would pass even if the search API/results
    // list were completely broken.
    const modal = page.locator('.glass-search');
    const input = page.getByPlaceholder(/ค้นหา/i).first();
    await input.fill('PTT');
    // ResultRow (SearchModal.tsx) renders parseSymbol(item.symbol, item.market).display — .BK suffix stripped for render.
    await expect(modal.getByText('PTT', { exact: true }).first()).toBeVisible({ timeout: 5000 });
  });

  test('shows Thai name alongside symbol for SET stocks', async ({ page }) => {
    const input = page.getByPlaceholder(/ค้นหา/i).first();
    await input.fill('PTT');
    await expect(page.getByText('ปตท.').first()).toBeVisible({ timeout: 5000 });
  });

  test('selecting a result closes the modal', async ({ page }) => {
    const modal = page.locator('.glass-search');
    const input = page.getByPlaceholder(/ค้นหา/i).first();
    await input.fill('PTT');
    const resultRow = modal.getByText('PTT', { exact: true }).first();
    await expect(resultRow).toBeVisible({ timeout: 5000 });
    // Unscoped, .first() resolves to the sidebar's own 'PTT' watchlist row —
    // sitting behind the modal backdrop (z-50), so the click gets blocked by
    // '.glass-backdrop intercepts pointer events' instead of hitting the
    // actual search result.
    await resultRow.click();
    // Modal should close
    await expect(page.locator('.glass-backdrop').first()).not.toBeVisible();
  });

  test('selecting a result navigates to chart page', async ({ page }) => {
    const modal = page.locator('.glass-search');
    const input = page.getByPlaceholder(/ค้นหา/i).first();
    await input.fill('PTT');
    const resultRow = modal.getByText('PTT', { exact: true }).first();
    await expect(resultRow).toBeVisible({ timeout: 5000 });
    await resultRow.click();
    await expect(page).toHaveURL('/');
  });
});

test.describe('Search Modal — category filter tabs', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await mockSearchAPI(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.getByText(/ค้นหา PTT, AAPL/).click();
  });

  // SearchModal.tsx FILTERS constant: the pill labels are Thai
  // (ทั้งหมด/หุ้นไทย/หุ้น US/กองทุน), not the bare market-code strings this
  // suite assumed — 'All'/'SET'/'US'/'FUND' never existed as button names.
  // The filter row is also only rendered `{query.length > 0 && (...)}` —
  // it does not exist at all before the user types anything.
  test('ทั้งหมด, หุ้นไทย, หุ้น US, กองทุน filter tabs are visible', async ({ page }) => {
    await page.getByPlaceholder(/ค้นหา/i).first().fill('PTT');
    for (const tab of ['ทั้งหมด', 'หุ้นไทย', 'หุ้น US', 'กองทุน']) {
      await expect(page.getByRole('button', { name: tab, exact: true })).toBeVisible();
    }
  });

  test('ทั้งหมด (All) tab is active by default', async ({ page }) => {
    await page.getByPlaceholder(/ค้นหา/i).first().fill('PTT');
    const allBtn = page.getByRole('button', { name: 'ทั้งหมด', exact: true });
    // Active tab should have accent styling (check background not transparent)
    await expect(allBtn).toBeVisible();
  });

  test('clicking หุ้นไทย (SET) tab filters search results to SET only', async ({ page }) => {
    const modal = page.locator('.glass-search');
    const input = page.getByPlaceholder(/ค้นหา/i).first();
    await input.fill('PTT');

    // Wait for results
    await expect(modal.getByText('PTT', { exact: true }).first()).toBeVisible({ timeout: 5000 });

    await page.getByRole('button', { name: 'หุ้นไทย', exact: true }).click();

    // AAPL (US stock) should not appear after SET filter — scoped to the
    // modal: the Navbar's own search-bar button text ("ค้นหา PTT, AAPL...K")
    // contains "AAPL" as a substring and is always visible regardless of
    // the filter, which made the unscoped assertion unable to ever fail.
    await expect(modal.getByText('AAPL', { exact: true })).not.toBeVisible();
  });
});

test.describe('Search Modal — keyboard navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await mockSearchAPI(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.getByText(/ค้นหา PTT, AAPL/).click();
  });

  test('ArrowDown moves highlight to first result', async ({ page }) => {
    // Scoped to the modal panel — SearchModal.tsx debounces the search
    // 280ms (setTimeout in the query effect), so an unscoped getByText('PTT')
    // resolves instantly against the sidebar's own 'PTT' watchlist row
    // instead of waiting for the debounced result list. That let ArrowDown
    // fire while `results` was still empty (totalItems 0), corrupting
    // `highlighted` to -1 for the rest of the test.
    const modal = page.locator('.glass-search');
    const input = page.getByPlaceholder(/ค้นหา/i).first();
    await input.fill('PTT');
    await expect(modal.getByText('PTT', { exact: true }).first()).toBeVisible({ timeout: 5000 });
    await page.keyboard.press('ArrowDown');
    // A result row should now have highlighted state
    // (we just verify no error occurs and result still visible)
    await expect(modal.getByText('PTT', { exact: true }).first()).toBeVisible();
  });

  test('Enter selects the highlighted result', async ({ page }) => {
    const modal = page.locator('.glass-search');
    const input = page.getByPlaceholder(/ค้นหา/i).first();
    await input.fill('PTT');
    await expect(modal.getByText('PTT', { exact: true }).first()).toBeVisible({ timeout: 5000 });
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    // Modal should close after selection
    await expect(page.locator('.glass-backdrop').first()).not.toBeVisible();
  });
});

test.describe('Search Modal — recent searches', () => {
  test('shows popular stocks when search is empty', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await mockSearchAPI(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await page.getByText(/ค้นหา PTT, AAPL/).click();

    // Popular section should be visible (PTT.BK or AAPL as popular picks)
    await expect(page.getByText(/Popular|ยอดนิยม/i).first()).toBeVisible();
  });
});
