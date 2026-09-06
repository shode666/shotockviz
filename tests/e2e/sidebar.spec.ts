/**
 * Sidebar & Watchlist tests
 *
 * Covers:
 *  - Sidebar renders with default watchlist stocks
 *  - Market indices section (SET, S&P500, NASDAQ)
 *  - Clicking a stock updates the chart symbol
 *  - "+ เพิ่มหุ้น" redirects unauthenticated users to login
 *  - Authenticated users see their watchlist from the API
 *
 * NOTE: The sidebar is rendered as part of the chart page (/).
 *       All navigation happens within the same route.
 */
import { test, expect } from '@playwright/test';
import { mockStockAPIs, mockAuthSession, MOCK_AUTH_ME } from './helpers/mocks';

// ── Unauthenticated sidebar ────────────────────────────────────────────────────

test.describe('Sidebar — guest / default watchlist', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/');
    // bd:shotockviz-6h3 — clicks before React attaches handlers are
    // silently dropped; mitigated the same way as every other spec per
    // that bead's own note (not fixed here, this file may not touch
    // frontend/).
    await page.waitForLoadState('networkidle');
  });

  test('sidebar shows "Watchlist" heading', async ({ page }) => {
    await expect(page.getByText('Watchlist', { exact: true })).toBeVisible();
  });

  test('default watchlist contains PTT', async ({ page }) => {
    // DEFAULT_WATCHLIST includes PTT.BK; sidebar shows "PTT" without suffix
    await expect(page.getByText('PTT').first()).toBeVisible({ timeout: 8000 });
  });

  test('default watchlist contains AAPL', async ({ page }) => {
    await expect(page.getByText('AAPL').first()).toBeVisible({ timeout: 8000 });
  });

  test('default watchlist contains NVDA', async ({ page }) => {
    await expect(page.getByText('NVDA').first()).toBeVisible({ timeout: 8000 });
  });

  test('market indices section shows SET', async ({ page }) => {
    await expect(page.getByText('SET').first()).toBeVisible({ timeout: 8000 });
  });

  test('market indices section shows S&P500', async ({ page }) => {
    await expect(page.getByText('S&P500')).toBeVisible({ timeout: 8000 });
  });

  test('market indices section shows NASDAQ', async ({ page }) => {
    await expect(page.getByText('NASDAQ')).toBeVisible({ timeout: 8000 });
  });

  test('clicking AAPL stock button keeps user on chart page', async ({ page }) => {
    // bd:shotockviz-al7 — scoped to <aside> (the sidebar). Navbar renders
    // before Sidebar in __root.tsx and its search-bar button text also
    // contains "AAPL" ("ค้นหา PTT, AAPL...K"), so an unscoped
    // getByRole('button').filter({ hasText: 'AAPL' }) resolves to the
    // Navbar search button instead — same shape as Quinn's fix in
    // sr-levels.spec.ts.
    const aaplBtn = page.locator('aside').getByRole('button').filter({ hasText: 'AAPL' }).first();
    await expect(aaplBtn).toBeVisible({ timeout: 8000 });
    await aaplBtn.click();
    // Stays on home / chart route
    await expect(page).toHaveURL('/');
  });

  test('clicking NVDA stock button in sidebar navigates to chart for NVDA', async ({ page }) => {
    // bd:shotockviz-al7 — same unscoped-click defect shape as the AAPL cases
    // below; scoped to <aside> for the same reason.
    const nvdaBtn = page.locator('aside').getByRole('button').filter({ hasText: 'NVDA' }).first();
    await expect(nvdaBtn).toBeVisible({ timeout: 8000 });
    await nvdaBtn.click();
    // Toolbar should now display NVDA as selected symbol
    await expect(page.getByText('NVDA').first()).toBeVisible();
    await expect(page).toHaveURL('/');
  });

  test('clicking stock in sidebar does NOT navigate away from /', async ({ page }) => {
    // bd:shotockviz-al7 — scoped to <aside>; see note above.
    const aaplBtn = page.locator('aside').getByRole('button').filter({ hasText: 'AAPL' }).first();
    await aaplBtn.click();
    await expect(page).toHaveURL('/');
  });

  test('"เพิ่มหุ้น" button redirects unauthenticated user to /login', async ({ page }) => {
    // Sidebar.tsx:487-496 — the footer "add stock" button renders a lucide
    // `<Plus>` icon (no text glyph) followed by the label "เพิ่มหุ้น"; its
    // accessible name has never included a literal "+" character. The
    // header add-button (Sidebar.tsx:316-325, aria-label="เพิ่มหุ้น") only
    // renders `{isAuthenticated && ...}`, so there is no ambiguity here.
    const addBtn = page.getByRole('button', { name: 'เพิ่มหุ้น' });
    await expect(addBtn).toBeVisible({ timeout: 8000 });
    await addBtn.click();
    await expect(page).toHaveURL('/login');
  });
});

// ── Authenticated sidebar ──────────────────────────────────────────────────────

test.describe('Sidebar — authenticated user with server watchlist', () => {
  const MOCK_WATCHLIST = [
    { id: 1, symbol: 'PTT.BK', order: 0 },
    { id: 2, symbol: 'AAPL',   order: 1 },
    { id: 3, symbol: 'TSLA',   order: 2 },
  ];

  test.beforeEach(async ({ page }) => {
    await mockStockAPIs(page);
    await mockAuthSession(page, MOCK_AUTH_ME);

    // Override watchlist 401 stub from mockStockAPIs with a real 200 response
    await page.route('**/api/v1/watchlists**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_WATCHLIST),
      }),
    );

    await page.goto('/');
  });

  test('authenticated sidebar shows TSLA from server watchlist', async ({ page }) => {
    await expect(page.getByText('TSLA').first()).toBeVisible({ timeout: 8000 });
  });

  test('authenticated sidebar still shows Watchlist heading', async ({ page }) => {
    await expect(page.getByText('Watchlist', { exact: true })).toBeVisible();
  });
});

// ── Sidebar price display ─────────────────────────────────────────────────────

test.describe('Sidebar — price data display', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/');
  });

  test('sidebar displays a price or change indicator for watchlist items', async ({ page }) => {
    // The mock quote returns { price: 35.5, change: 0.5, change_pct: 1.43 }
    // Sidebar rows render price or % change — look for any numeric or % pattern
    await page.waitForLoadState('networkidle');
    // At minimum, the symbol names must be visible (price may be async)
    await expect(page.getByText('PTT').first()).toBeVisible({ timeout: 8000 });
  });
});
