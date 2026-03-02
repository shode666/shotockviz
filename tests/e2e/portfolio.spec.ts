/**
 * Portfolio page tests
 * Covers: page load, auth redirect, empty state, add-transaction modal.
 */
import { test, expect } from '@playwright/test';
import { mockStockAPIs, mockAuthSession, MOCK_AUTH_ME } from './helpers/mocks';

const MOCK_PORTFOLIO = [
  {
    id: 1,
    symbol: 'PTT.BK',
    quantity: 1000,
    avg_price: 32.5,
    current_price: 35.5,
    gain_loss: 3000,
    gain_loss_pct: 9.23,
  },
  {
    id: 2,
    symbol: 'AAPL',
    quantity: 10,
    avg_price: 175.0,
    current_price: 187.42,
    gain_loss: 124.2,
    gain_loss_pct: 7.1,
  },
];

async function mockPortfolioAPI(page: any, data = MOCK_PORTFOLIO) {
  await page.route('**/api/portfolio**', (route: any) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(data),
    }),
  );
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
    await expect(page.getByText('PTT.BK').first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('AAPL').first()).toBeVisible();
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
    await expect(page.getByText(/9\.23%|7\.1%/).first()).toBeVisible({ timeout: 8000 });
  });
});

test.describe('Portfolio Page — empty state', () => {
  test('shows empty state when portfolio is empty', async ({ page }) => {
    await mockStockAPIs(page);
    await mockAuthSession(page, MOCK_AUTH_ME);
    await page.route('**/api/portfolio**', (route) =>
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
