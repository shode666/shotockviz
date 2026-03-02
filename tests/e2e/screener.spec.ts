/**
 * Stock Screener page tests
 */
import { test, expect } from '@playwright/test';
import { mockStockAPIs, mockScreener, MOCK_SCREENER_RESULTS } from './helpers/mocks';

test.describe('Screener Page — initial state', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/screener');
  });

  test('shows page heading "Stock Screener"', async ({ page }) => {
    await expect(page.getByText('Stock Screener')).toBeVisible();
  });

  test('shows descriptive subtitle', async ({ page }) => {
    await expect(page.getByText('กรองหุ้นด้วยเงื่อนไขที่ต้องการ')).toBeVisible();
  });

  test('shows Run Screen button', async ({ page }) => {
    await expect(page.getByRole('button', { name: /Run Screen/ })).toBeVisible();
  });

  test('shows Save Filter button', async ({ page }) => {
    await expect(page.getByRole('button', { name: /Save Filter/ })).toBeVisible();
  });

  test('shows all 5 filter dropdowns', async ({ page }) => {
    // Filter labels appear as uppercase text above each select
    const filterLabels = ['market', 'rsi', 'volume', 'macd', 'price'];
    for (const label of filterLabels) {
      await expect(page.getByText(label, { exact: false }).first()).toBeVisible();
    }
    // All selects should be present
    const selects = page.locator('select');
    await expect(selects).toHaveCount(5);
  });

  test('market filter defaults to "SET + US"', async ({ page }) => {
    const marketSelect = page.locator('select').nth(0);
    await expect(marketSelect).toHaveValue('SET + US');
  });

  test('rsi filter defaults to "< 30 (Oversold)"', async ({ page }) => {
    const rsiSelect = page.locator('select').nth(1);
    await expect(rsiSelect).toHaveValue('< 30 (Oversold)');
  });

  test('shows "กด ▶ Run Screen" placeholder before first run', async ({ page }) => {
    await expect(page.getByText('ตั้งค่าเงื่อนไขแล้วกด ▶ Run Screen')).toBeVisible();
  });

  test('shows Export CSV button', async ({ page }) => {
    await expect(page.getByRole('button', { name: /Export CSV/ })).toBeVisible();
  });

  test('table headers are visible', async ({ page }) => {
    const headers = ['Symbol', 'ชื่อบริษัท', 'ราคา', 'เปลี่ยนแปลง', 'RSI', 'MACD', 'Volume', 'Signal'];
    for (const h of headers) {
      await expect(page.getByRole('columnheader', { name: h })).toBeVisible();
    }
  });
});

test.describe('Screener Page — filter interaction', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/screener');
  });

  test('can change market filter to SET', async ({ page }) => {
    const marketSelect = page.locator('select').nth(0);
    await marketSelect.selectOption('SET');
    await expect(marketSelect).toHaveValue('SET');
  });

  test('can change rsi filter to Any', async ({ page }) => {
    const rsiSelect = page.locator('select').nth(1);
    await rsiSelect.selectOption('Any');
    await expect(rsiSelect).toHaveValue('Any');
  });

  test('can change macd filter to Sell Signal', async ({ page }) => {
    const macdSelect = page.locator('select').nth(3);
    await macdSelect.selectOption('Sell Signal');
    await expect(macdSelect).toHaveValue('Sell Signal');
  });
});

test.describe('Screener Page — Run Screen flow', () => {
  test('shows loading skeleton when Run Screen is clicked', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);

    // Delay screener response so we can observe loading state
    await page.route('**/api/screener**', async (route) => {
      await new Promise((resolve) => setTimeout(resolve, 500));
      await route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify(MOCK_SCREENER_RESULTS),
      });
    });

    await page.goto('/screener');

    await page.getByRole('button', { name: /Run Screen/ }).click();

    // Loading text should appear in the table header area
    await expect(page.getByText('กำลังค้นหา…').first()).toBeVisible();
  });

  test('displays results after Run Screen', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await mockScreener(page, MOCK_SCREENER_RESULTS);

    await page.goto('/screener');

    await page.getByRole('button', { name: /Run Screen/ }).click();

    // Wait for results count header
    await expect(page.getByText(`ผลลัพธ์ ${MOCK_SCREENER_RESULTS.length} หุ้น`)).toBeVisible();

    // AAPL and NVDA rows should be visible
    await expect(page.getByRole('cell', { name: 'AAPL' })).toBeVisible();
    await expect(page.getByRole('cell', { name: 'NVDA' })).toBeVisible();
  });

  test('shows "Strong Buy" signal badge', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await mockScreener(page, MOCK_SCREENER_RESULTS);

    await page.goto('/screener');
    await page.getByRole('button', { name: /Run Screen/ }).click();

    await expect(page.getByText('Strong Buy').first()).toBeVisible();
  });

  test('shows empty state when no results match', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await mockScreener(page, []); // empty results

    await page.goto('/screener');
    await page.getByRole('button', { name: /Run Screen/ }).click();

    await expect(page.getByText('ไม่พบหุ้นที่ตรงกับเงื่อนไข')).toBeVisible();
  });

  test('clicking a result row navigates to chart page', async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await mockScreener(page, MOCK_SCREENER_RESULTS);

    await page.goto('/screener');
    await page.getByRole('button', { name: /Run Screen/ }).click();

    // Wait for results
    await expect(page.getByRole('cell', { name: 'AAPL' })).toBeVisible();

    // Click the AAPL row
    await page.getByRole('cell', { name: 'AAPL' }).click();

    // Should navigate to /
    await expect(page).toHaveURL('/');
  });
});
