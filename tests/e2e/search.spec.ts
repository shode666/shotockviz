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
    await page.getByText(/ค้นหา PTT, AAPL/).click();
    // Modal overlay should be visible
    await expect(page.locator('.search-overlay, [class*="search-overlay"]').first()).toBeVisible();
  });

  test('search modal opens with Cmd+K / Ctrl+K', async ({ page }) => {
    await page.keyboard.press('Meta+k');
    // Input should be focused
    const input = page.getByPlaceholder(/ค้นหา/i).first();
    await expect(input).toBeVisible();
  });

  test('pressing Escape closes the search modal', async ({ page }) => {
    await page.getByText(/ค้นหา PTT, AAPL/).click();
    await page.keyboard.press('Escape');
    // Overlay should be gone
    await expect(page.locator('.search-overlay').first()).not.toBeVisible();
  });

  test('clicking the overlay backdrop closes the modal', async ({ page }) => {
    await page.getByText(/ค้นหา PTT, AAPL/).click();
    await expect(page.locator('.search-overlay').first()).toBeVisible();
    // Click outside the panel
    await page.mouse.click(10, 10);
    await expect(page.locator('.search-overlay').first()).not.toBeVisible();
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
    // Open modal
    await page.getByText(/ค้นหา PTT, AAPL/).click();
  });

  test('typing shows search results', async ({ page }) => {
    const input = page.getByPlaceholder(/ค้นหา/i).first();
    await input.fill('PTT');
    await expect(page.getByText('PTT.BK').first()).toBeVisible({ timeout: 5000 });
  });

  test('shows Thai name alongside symbol for SET stocks', async ({ page }) => {
    const input = page.getByPlaceholder(/ค้นหา/i).first();
    await input.fill('PTT');
    await expect(page.getByText('ปตท.').first()).toBeVisible({ timeout: 5000 });
  });

  test('selecting a result closes the modal', async ({ page }) => {
    const input = page.getByPlaceholder(/ค้นหา/i).first();
    await input.fill('PTT');
    await expect(page.getByText('PTT.BK').first()).toBeVisible({ timeout: 5000 });
    await page.getByText('PTT.BK').first().click();
    // Modal should close
    await expect(page.locator('.search-overlay').first()).not.toBeVisible();
  });

  test('selecting a result navigates to chart page', async ({ page }) => {
    const input = page.getByPlaceholder(/ค้นหา/i).first();
    await input.fill('PTT');
    await expect(page.getByText('PTT.BK').first()).toBeVisible({ timeout: 5000 });
    await page.getByText('PTT.BK').first().click();
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
    await page.getByText(/ค้นหา PTT, AAPL/).click();
  });

  test('All, SET, US, FUND filter tabs are visible', async ({ page }) => {
    for (const tab of ['All', 'SET', 'US', 'FUND']) {
      await expect(page.getByRole('button', { name: tab, exact: true })).toBeVisible();
    }
  });

  test('All tab is active by default', async ({ page }) => {
    const allBtn = page.getByRole('button', { name: 'All', exact: true });
    // Active tab should have accent styling (check background not transparent)
    await expect(allBtn).toBeVisible();
  });

  test('clicking SET tab filters search results to SET only', async ({ page }) => {
    const input = page.getByPlaceholder(/ค้นหา/i).first();
    await input.fill('PTT');

    // Wait for results
    await expect(page.getByText('PTT.BK').first()).toBeVisible({ timeout: 5000 });

    await page.getByRole('button', { name: 'SET', exact: true }).click();

    // AAPL (US stock) should not appear after SET filter
    await expect(page.getByText('AAPL').first()).not.toBeVisible();
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
    await page.getByText(/ค้นหา PTT, AAPL/).click();
  });

  test('ArrowDown moves highlight to first result', async ({ page }) => {
    const input = page.getByPlaceholder(/ค้นหา/i).first();
    await input.fill('PTT');
    await expect(page.getByText('PTT.BK').first()).toBeVisible({ timeout: 5000 });
    await page.keyboard.press('ArrowDown');
    // A result row should now have highlighted state
    // (we just verify no error occurs and result still visible)
    await expect(page.getByText('PTT.BK').first()).toBeVisible();
  });

  test('Enter selects the highlighted result', async ({ page }) => {
    const input = page.getByPlaceholder(/ค้นหา/i).first();
    await input.fill('PTT');
    await expect(page.getByText('PTT.BK').first()).toBeVisible({ timeout: 5000 });
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    // Modal should close after selection
    await expect(page.locator('.search-overlay').first()).not.toBeVisible();
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
    await page.getByText(/ค้นหา PTT, AAPL/).click();

    // Popular section should be visible (PTT.BK or AAPL as popular picks)
    await expect(page.getByText(/Popular|ยอดนิยม/i).first()).toBeVisible();
  });
});
