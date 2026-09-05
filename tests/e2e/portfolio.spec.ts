/**
 * Portfolio page tests
 * Covers: page load, auth redirect, empty state, add-transaction modal.
 */
import { test, expect } from '@playwright/test';
import { mockStockAPIs, mockAuthSession, MOCK_AUTH_ME } from './helpers/mocks';

// Shape matches backend/models/schemas.py HoldingResponse — PortfolioPage.tsx
// reads `analytics?.holdings` (PortfolioAnalytics), not a flat holdings array.
// The old flat MOCK_PORTFOLIO (quantity/avg_price/gain_loss field names) was
// never valid against either GET /portfolio (TransactionResponse: qty/price/
// type/fee/currency/date) or GET /portfolio/analytics (PortfolioAnalytics:
// {..., holdings: HoldingResponse[]}) — HoldingsTable.tsx's holdings prop
// always resolved to [] and rendered "ยังไม่มีหุ้นในพอร์ต", so the two tests
// below that expected holdings/gain-loss text to appear only ever passed by
// accident (matching an unrelated element elsewhere in the DOM), not by
// actually exercising the Holdings table. See Quinn's finding on
// bd:shotockviz-c73.
const MOCK_HOLDINGS = [
  {
    symbol: 'PTT.BK',
    qty: 1000,
    avg_cost: 32.5,
    current_price: 35.5,
    current_value: 35500,
    unrealized_pl: 3000,
    unrealized_pl_pct: 9.23,
    currency: 'THB',
  },
  {
    symbol: 'AAPL',
    qty: 10,
    avg_cost: 175.0,
    current_price: 187.42,
    current_value: 1874.2,
    unrealized_pl: 124.2,
    unrealized_pl_pct: 7.1,
    currency: 'USD',
  },
];

const MOCK_ANALYTICS = {
  base_currency: 'THB',
  total_value: 37374.2,
  total_cost: 34250,
  unrealized_pl: 3124.2,
  unrealized_pl_pct: 9.12,
  holdings: MOCK_HOLDINGS,
  has_pending_prices: false,
};

const MOCK_TRANSACTIONS = [
  { id: 1, symbol: 'PTT.BK', type: 'buy', qty: 1000, price: 32.5, fee: 0, currency: 'THB', date: '2024-01-01', created_at: '2024-01-01T00:00:00Z' },
  { id: 2, symbol: 'AAPL', type: 'buy', qty: 10, price: 175.0, fee: 0, currency: 'USD', date: '2024-01-02', created_at: '2024-01-02T00:00:00Z' },
];

async function mockPortfolioAPI(page: any, { holdings = MOCK_HOLDINGS, txns = MOCK_TRANSACTIONS } = {}) {
  await page.route('**/api/v1/portfolio**', (route: any) => {
    const url = route.request().url();
    if (url.includes('/analytics')) {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ ...MOCK_ANALYTICS, holdings }),
      });
    }
    if (url.includes('/performance')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(txns) });
  });
}

test.describe('Portfolio Page — unauthenticated', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
  });

  test('shows portfolio page at /portfolio', async ({ page }) => {
    await page.goto('/portfolio');
    await expect(page).toHaveURL('/portfolio');
  });

  test('shows "Portfolio" heading', async ({ page }) => {
    await page.goto('/portfolio');
    await expect(page.getByText('Portfolio', { exact: false }).first()).toBeVisible();
  });

  test('prompts user to login when unauthenticated', async ({ page }) => {
    await page.goto('/portfolio');
    // Page should show login prompt or empty state
    await expect(
      page.getByText(/เข้าสู่ระบบ|login|ยังไม่ได้/i).first()
    ).toBeVisible({ timeout: 5000 });
  });
});

test.describe('Portfolio Page — authenticated', () => {
  test.beforeEach(async ({ page }) => {
    await mockStockAPIs(page);
    await mockAuthSession(page, MOCK_AUTH_ME);
    await mockPortfolioAPI(page);
    await page.goto('/portfolio');
  });

  test('shows portfolio table with holdings', async ({ page }) => {
    // HoldingsTable.tsx renders displaySymbol(h.symbol) — .BK suffix stripped
    // for render. Scoped to the holdings table's own symbol cell
    // (HoldingsTable.tsx td.font-semibold), not "PTT text anywhere on the
    // page" — the sidebar can transiently render an unrelated 'PTT' row
    // during the guest->authenticated hydration window, which made the old
    // bare getByText('PTT') pass for the wrong reason.
    // Not exact: the symbol cell is a bare text node ("PTT") sibling to a
    // separate currency-badge <span>THB</span> inside the same <td>
    // (HoldingsTable.tsx) — there is no element whose OWN text is exactly
    // "PTT", only one whose text contains it.
    const table = page.locator('table');
    await expect(table.getByText('PTT').first()).toBeVisible({ timeout: 8000 });
    await expect(table.getByText('AAPL').first()).toBeVisible();
  });

  test('"+ เพิ่มรายการ" or Add Transaction button is visible', async ({ page }) => {
    const addBtn = page.getByRole('button', { name: /เพิ่มรายการ|Add Transaction/i });
    await expect(addBtn).toBeVisible({ timeout: 5000 });
  });

  test('clicking Add Transaction opens modal', async ({ page }) => {
    const addBtn = page.getByRole('button', { name: /เพิ่มรายการ|Add Transaction/i });
    await addBtn.click();
    // Modal should appear with glass-panel style
    await expect(page.locator('.glass-panel').first()).toBeVisible();
  });

  test('Add Transaction modal has Symbol input', async ({ page }) => {
    const addBtn = page.getByRole('button', { name: /เพิ่มรายการ|Add Transaction/i });
    await addBtn.click();
    await expect(page.getByPlaceholder(/symbol|หลักทรัพย์/i).first()).toBeVisible({ timeout: 5000 });
  });

  test('Add Transaction modal has Quantity input', async ({ page }) => {
    const addBtn = page.getByRole('button', { name: /เพิ่มรายการ|Add Transaction/i });
    await addBtn.click();
    await expect(page.getByPlaceholder(/จำนวน|quantity/i).first()).toBeVisible({ timeout: 5000 });
  });

  test('Add Transaction modal has Price input', async ({ page }) => {
    const addBtn = page.getByRole('button', { name: /เพิ่มรายการ|Add Transaction/i });
    await addBtn.click();
    await expect(page.getByPlaceholder(/ราคา|price/i).first()).toBeVisible({ timeout: 5000 });
  });

  test('Add Transaction modal closes on cancel/close button', async ({ page }) => {
    const addBtn = page.getByRole('button', { name: /เพิ่มรายการ|Add Transaction/i });
    await addBtn.click();
    await expect(page.locator('.glass-panel').first()).toBeVisible();

    // Find and click close button (X or ยกเลิก)
    const closeBtn = page.getByRole('button', { name: /ยกเลิก|close|ปิด/i }).first();
    await closeBtn.click();
    await expect(page.locator('.glass-overlay').first()).not.toBeVisible();
  });

  test('portfolio shows gain/loss percentage', async ({ page }) => {
    // Should show positive gain in green
    await expect(page.locator('table').getByText(/9\.23%|7\.1%/).first()).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Portfolio Page — empty state', () => {
  test('shows empty state when portfolio is empty', async ({ page }) => {
    await mockStockAPIs(page);
    await mockAuthSession(page, MOCK_AUTH_ME);
    await page.route('**/api/v1/portfolio**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      }),
    );
    await page.goto('/portfolio');
    // Should show empty/no holdings message
    await expect(
      page.getByText(/ยังไม่มี|ว่างเปล่า|no holdings|empty/i).first()
    ).toBeVisible({ timeout: 8000 });
  });
});
