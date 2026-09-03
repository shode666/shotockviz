/**
 * Alerts page tests
 * Covers: page load, create-alert modal, alert list, delete alert.
 */
import { test, expect } from '@playwright/test';
import { mockStockAPIs, mockAuthSession, MOCK_AUTH_ME } from './helpers/mocks';

const MOCK_ALERTS = [
  {
    id: 1,
    symbol: 'PTT.BK',
    condition: 'above',
    price: 40.0,
    active: true,
    created_at: '2024-01-15T10:30:00Z',
  },
  {
    id: 2,
    symbol: 'AAPL',
    condition: 'below',
    price: 170.0,
    active: true,
    created_at: '2024-01-14T09:00:00Z',
  },
];

async function mockAlertsAPI(page: any, data = MOCK_ALERTS) {
  await page.route('**/api/v1/alerts**', (route: any) => {
    if (route.request().method() === 'GET') {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(data),
      });
    } else {
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ id: 99, ...data[0] }),
      });
    }
  });
}

test.describe('Alerts Page — layout', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/alerts');
  });

  test('shows Alerts page at /alerts', async ({ page }) => {
    await expect(page).toHaveURL('/alerts');
  });

  test('shows "Alerts" heading', async ({ page }) => {
    await expect(page.getByText('Alerts', { exact: false }).first()).toBeVisible();
  });

  test('shows "+ สร้าง Alert" or Create Alert button', async ({ page }) => {
    await expect(
      page.getByRole('button', { name: /สร้าง Alert|Create Alert|เพิ่ม/i }).first()
    ).toBeVisible();
  });
});

test.describe('Alerts Page — unauthenticated state', () => {
  test('shows login prompt when not authenticated', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/alerts');
    await expect(
      page.getByText(/เข้าสู่ระบบ|login|กรุณา/i).first()
    ).toBeVisible({ timeout: 5000 });
  });
});

test.describe('Alerts Page — authenticated with alerts', () => {
  test.beforeEach(async ({ page }) => {
    await mockStockAPIs(page);
    await mockAuthSession(page, MOCK_AUTH_ME);
    await mockAlertsAPI(page);
    await page.goto('/alerts');
  });

  test('shows alert list with PTT.BK and AAPL', async ({ page }) => {
    await expect(page.getByText('PTT.BK').first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText('AAPL').first()).toBeVisible();
  });

  test('shows alert condition (above/below) for each alert', async ({ page }) => {
    await expect(page.getByText(/above|Above|เกิน/i).first()).toBeVisible({ timeout: 8000 });
    await expect(page.getByText(/below|Below|ต่ำกว่า/i).first()).toBeVisible();
  });

  test('shows target price for each alert', async ({ page }) => {
    await expect(page.getByText(/40\.00|40/i).first()).toBeVisible({ timeout: 8000 });
  });

  test('shows delete button for each alert', async ({ page }) => {
    await page.waitForSelector('text=PTT.BK', { timeout: 8000 });
    // Delete button (trash icon or ลบ text) should be visible
    const deleteBtn = page.getByRole('button', { name: /delete|ลบ/i }).first();
    await expect(deleteBtn).toBeVisible();
  });
});

test.describe('Alerts Page — Create Alert Modal', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/alerts');
  });

  test('clicking "+ สร้าง Alert" opens modal', async ({ page }) => {
    const createBtn = page.getByRole('button', { name: /สร้าง Alert|Create Alert|เพิ่ม/i }).first();
    await createBtn.click();
    await expect(page.locator('.glass-panel').first()).toBeVisible();
  });

  test('modal has Symbol input field', async ({ page }) => {
    const createBtn = page.getByRole('button', { name: /สร้าง Alert|Create Alert|เพิ่ม/i }).first();
    await createBtn.click();
    await expect(page.getByPlaceholder(/symbol|หุ้น/i).first()).toBeVisible({ timeout: 5000 });
  });

  test('modal has Price/Target input field', async ({ page }) => {
    const createBtn = page.getByRole('button', { name: /สร้าง Alert|Create Alert|เพิ่ม/i }).first();
    await createBtn.click();
    await expect(page.getByPlaceholder(/ราคา|price|target/i).first()).toBeVisible({ timeout: 5000 });
  });

  test('modal has Above/Below condition selector', async ({ page }) => {
    const createBtn = page.getByRole('button', { name: /สร้าง Alert|Create Alert|เพิ่ม/i }).first();
    await createBtn.click();
    const conditionSelect = page.locator('select').first();
    await expect(conditionSelect).toBeVisible({ timeout: 5000 });
  });

  test('modal closes when cancel button is clicked', async ({ page }) => {
    const createBtn = page.getByRole('button', { name: /สร้าง Alert|Create Alert|เพิ่ม/i }).first();
    await createBtn.click();
    await expect(page.locator('.glass-panel').first()).toBeVisible();

    const closeBtn = page.getByRole('button', { name: /ยกเลิก|cancel|close|ปิด/i }).first();
    await closeBtn.click();
    await expect(page.locator('.glass-overlay').first()).not.toBeVisible();
  });

  test('modal closes on backdrop click', async ({ page }) => {
    const createBtn = page.getByRole('button', { name: /สร้าง Alert|Create Alert|เพิ่ม/i }).first();
    await createBtn.click();
    await expect(page.locator('.glass-overlay').first()).toBeVisible();

    // Click the overlay backdrop
    const overlay = page.locator('.glass-overlay').first();
    const box = await overlay.boundingBox();
    if (box) {
      await page.mouse.click(box.x + 10, box.y + 10);
    }
    await expect(page.locator('.glass-overlay').first()).not.toBeVisible();
  });
});

test.describe('Alerts Page — empty state', () => {
  test('shows empty state when no alerts exist', async ({ page }) => {
    await mockStockAPIs(page);
    await mockAuthSession(page, MOCK_AUTH_ME);
    await page.route('**/api/v1/alerts**', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([]),
      }),
    );
    await page.goto('/alerts');
    await expect(
      page.getByText(/ยังไม่มี|ไม่มี Alert|no alerts|empty/i).first()
    ).toBeVisible({ timeout: 8000 });
  });
});
