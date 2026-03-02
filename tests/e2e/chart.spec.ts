/**
 * Chart page (home "/") tests
 */
import { test, expect } from '@playwright/test';
import { mockStockAPIs } from './helpers/mocks';

test.describe('Chart Page — toolbar', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/');
  });

  test('default selected stock is PTT.BK', async ({ page }) => {
    // ChartToolbar renders the stock symbol
    await expect(page.getByText('PTT.BK').first()).toBeVisible();
  });

  test('timeframe buttons are all visible', async ({ page }) => {
    const timeframes = ['1m', '5m', '15m', '1h', '4h', '1D', '1W', '1M'];
    for (const tf of timeframes) {
      await expect(page.getByRole('button', { name: tf, exact: true })).toBeVisible();
    }
  });

  test('1D is the default active timeframe', async ({ page }) => {
    // The active button has btn-accent class
    const activeBtn = page.getByRole('button', { name: '1D', exact: true });
    await expect(activeBtn).toBeVisible();
    await expect(activeBtn).toHaveClass(/btn-accent/);
  });

  test('clicking a timeframe button changes selection', async ({ page }) => {
    const weekBtn = page.getByRole('button', { name: '1W', exact: true });
    await weekBtn.click();
    await expect(weekBtn).toHaveClass(/btn-accent/);

    // 1D should no longer be active
    const dayBtn = page.getByRole('button', { name: '1D', exact: true });
    await expect(dayBtn).not.toHaveClass(/btn-accent/);
  });

  test('chart type buttons are visible (candlestick, line, area)', async ({ page }) => {
    // Emoji icon buttons for chart type
    await expect(page.getByRole('button', { name: '🕯️' })).toBeVisible();
    await expect(page.getByRole('button', { name: '📉' })).toBeVisible();
    await expect(page.getByRole('button', { name: '▬' })).toBeVisible();
  });

  test('indicator buttons are visible', async ({ page }) => {
    const indicators = ['MA 20', 'EMA 50', 'RSI 14', 'MACD', 'BB'];
    for (const ind of indicators) {
      await expect(page.getByRole('button', { name: ind, exact: true })).toBeVisible();
    }
  });

  test('clicking an indicator toggles it active', async ({ page }) => {
    const rsiBtn = page.getByRole('button', { name: 'RSI 14', exact: true });
    await expect(rsiBtn).toBeVisible();
    await rsiBtn.click();
    // After click it should have the active violet style (bg-violet-500)
    await expect(rsiBtn).toHaveClass(/bg-violet-500/);
  });
});

test.describe('Chart Page — sidebar', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/');
  });

  test('sidebar shows "Watchlist" heading', async ({ page }) => {
    await expect(page.getByText('Watchlist', { exact: true })).toBeVisible();
  });

  test('default watchlist shows PTT and AAPL for guests', async ({ page }) => {
    // DEFAULT_WATCHLIST shows symbol without .BK suffix
    await expect(page.getByText('PTT').first()).toBeVisible();
    await expect(page.getByText('AAPL').first()).toBeVisible();
  });

  test('market indices are shown (SET, S&P500, NASDAQ)', async ({ page }) => {
    await expect(page.getByText('SET').first()).toBeVisible();
    await expect(page.getByText('S&P500')).toBeVisible();
    await expect(page.getByText('NASDAQ')).toBeVisible();
  });

  test('clicking a watchlist stock navigates to home chart', async ({ page }) => {
    // Click AAPL in watchlist
    const aaplRow = page.getByRole('button').filter({ hasText: 'AAPL' }).first();
    await aaplRow.click();
    // Should still be on /
    await expect(page).toHaveURL('/');
  });
});

test.describe('Chart Page — chart canvas', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/');
  });

  test('chart canvas element is rendered', async ({ page }) => {
    // lightweight-charts renders a <canvas> inside the chart container
    const canvas = page.locator('canvas').first();
    await expect(canvas).toBeVisible({ timeout: 10_000 });
  });
});
