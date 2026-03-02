/**
 * Chart — timeframe switching & API call verification
 *
 * Covers:
 *  - All 8 timeframe buttons are clickable
 *  - Switching TF sends a new /history request with correct ?tf= param
 *  - Active button highlights
 *  - Chart canvas renders after data loads
 *  - Chart type switching (candlestick → line → area)
 */
import { test, expect } from '@playwright/test';
import { mockStockAPIs } from './helpers/mocks';

test.describe('Chart — timeframe buttons', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/');
    // Wait for chart to finish initial load
    await page.waitForLoadState('networkidle');
  });

  test('all 8 timeframe buttons are rendered', async ({ page }) => {
    const tfs = ['1m', '5m', '15m', '1h', '4h', '1D', '1W', '1M'];
    for (const tf of tfs) {
      await expect(page.getByRole('button', { name: tf, exact: true })).toBeVisible();
    }
  });

  test('1D is the default active timeframe (btn-accent class)', async ({ page }) => {
    const btn = page.getByRole('button', { name: '1D', exact: true });
    await expect(btn).toHaveClass(/btn-accent/);
  });

  test('clicking 1W makes it active and deactivates 1D', async ({ page }) => {
    const weekBtn = page.getByRole('button', { name: '1W', exact: true });
    const dayBtn = page.getByRole('button', { name: '1D', exact: true });
    await weekBtn.click();
    await expect(weekBtn).toHaveClass(/btn-accent/);
    await expect(dayBtn).not.toHaveClass(/btn-accent/);
  });

  test('clicking each timeframe triggers a /history API call with correct tf param', async ({ page }) => {
    const tfsToTest = ['1W', '1M', '4h', '1h'];
    for (const tf of tfsToTest) {
      const [request] = await Promise.all([
        page.waitForRequest((req) =>
          req.url().includes('/history') && req.url().includes(`tf=${tf}`),
        ),
        page.getByRole('button', { name: tf, exact: true }).click(),
      ]);
      expect(request.url()).toContain(`tf=${tf}`);
    }
  });

  test('clicking 5m triggers history request for 5m', async ({ page }) => {
    const [request] = await Promise.all([
      page.waitForRequest((req) => req.url().includes('/history') && req.url().includes('tf=5m')),
      page.getByRole('button', { name: '5m', exact: true }).click(),
    ]);
    expect(request.url()).toContain('tf=5m');
    expect(request.url()).toContain('/history');
  });

  test('switching TF multiple times does not cause error state', async ({ page }) => {
    const order = ['1W', '4h', '1M', '1D'];
    for (const tf of order) {
      await page.getByRole('button', { name: tf, exact: true }).click();
      await page.waitForTimeout(100);
    }
    // Chart canvas still present — no crash
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 10_000 });
    // No error toast visible
    await expect(page.getByText(/error|ผิดพลาด/i)).not.toBeVisible();
  });
});

test.describe('Chart — chart type switching', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('candlestick button is visible', async ({ page }) => {
    const candleBtn = page.locator('button[title="Candlestick"]');
    await expect(candleBtn).toBeVisible();
  });

  test('line chart button is visible', async ({ page }) => {
    await expect(page.locator('button[title="Line"]')).toBeVisible();
  });

  test('area chart button is visible', async ({ page }) => {
    await expect(page.locator('button[title="Area"]')).toBeVisible();
  });

  test('clicking line chart type activates it', async ({ page }) => {
    const lineBtn = page.locator('button[title="Line"]');
    await lineBtn.click();
    await expect(lineBtn).toHaveClass(/btn-accent/);
  });

  test('clicking candlestick after line restores candlestick', async ({ page }) => {
    await page.locator('button[title="Line"]').click();
    const candleBtn = page.locator('button[title="Candlestick"]');
    await candleBtn.click();
    await expect(candleBtn).toHaveClass(/btn-accent/);
  });

  test('canvas is rendered after chart type switch', async ({ page }) => {
    await page.locator('button[title="Area"]').click();
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 10_000 });
  });
});

test.describe('Chart — indicator toggles', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  const indicators = ['MA 20', 'EMA 50', 'RSI 14', 'MACD', 'BB'];

  for (const ind of indicators) {
    test(`${ind} button toggles to active state`, async ({ page }) => {
      const btn = page.getByRole('button', { name: ind, exact: true });
      await expect(btn).toBeVisible();
      await btn.click();
      await expect(btn).toHaveClass(/bg-violet-500/);
    });
  }

  test('toggling indicator twice deactivates it', async ({ page }) => {
    const btn = page.getByRole('button', { name: 'RSI 14', exact: true });
    await btn.click(); // activate
    await expect(btn).toHaveClass(/bg-violet-500/);
    await btn.click(); // deactivate
    await expect(btn).not.toHaveClass(/bg-violet-500/);
  });
});

test.describe('Chart — canvas render', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/');
  });

  test('canvas element renders within 10 seconds', async ({ page }) => {
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 10_000 });
  });

  test('canvas has non-zero dimensions', async ({ page }) => {
    const canvas = page.locator('canvas').first();
    await canvas.waitFor({ state: 'visible', timeout: 10_000 });
    const box = await canvas.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.width).toBeGreaterThan(0);
    expect(box!.height).toBeGreaterThan(0);
  });
});
