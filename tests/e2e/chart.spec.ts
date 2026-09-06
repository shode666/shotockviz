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
    // bd:shotockviz-6h3 — clicks that land before React attaches handlers
    // are silently dropped (confirmed not limited to the two controls the
    // bead names; the timeframe buttons below show the same symptom
    // without this wait). Mitigated the same way as every other spec
    // (search.spec.ts, sr-levels.spec.ts) per that bead's own note — not
    // fixed here, this file may not touch frontend/.
    await page.waitForLoadState('networkidle');
  });

  test('default selected stock is NVDA', async ({ page }) => {
    // appStore.ts:91 sets the default selectedStock.sym to 'NVDA', not
    // 'PTT.BK' (this test's original premise was wrong on the symbol
    // itself, not just the .BK suffix — a bare getByText('PTT') would have
    // passed anyway since PTT is elsewhere in the guest watchlist, without
    // proving anything about *selection*). Assert the toolbar's own
    // selected-stock span (ChartToolbar.tsx:32) instead of "text exists
    // somewhere on the page".
    await expect(page.locator('span.font-bold.text-sm').first()).toHaveText('NVDA');
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
    // ChartToolbar.tsx renders lucide icons with a `title` attribute
    // (Candlestick/Line/Area) — never emoji. See chart-timeframes.spec.ts
    // which already asserts these same buttons this way.
    await expect(page.getByRole('button', { name: 'Candlestick' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Line' })).toBeVisible();
    await expect(page.getByRole('button', { name: 'Area' })).toBeVisible();
  });

  test('indicator buttons are visible', async ({ page }) => {
    const indicators = ['MA 20', 'EMA 50', 'RSI 14', 'MACD', 'BB'];
    for (const ind of indicators) {
      await expect(page.getByRole('button', { name: ind, exact: true })).toBeVisible();
    }
  });

  test('clicking an indicator toggles it active', async ({ page }) => {
    // MA 20, not RSI 14 — ChartPage.tsx:36 makes RSI 14 + MACD default-on
    // ("replaces the old BottomPanel tabs"), so a first click on either of
    // those turns it OFF, not on. See chart-timeframes.spec.ts's dedicated
    // default-on-vs-default-off coverage.
    const maBtn = page.getByRole('button', { name: 'MA 20', exact: true });
    await expect(maBtn).toBeVisible();
    await expect(maBtn).toHaveAttribute('aria-pressed', 'false');
    await maBtn.click();
    // ChartToolbar.tsx applies the active indicator color via a Tailwind
    // arbitrary-value class (`bg-[var(--color-accent-strong)]`), never
    // `bg-violet-500` (that class only ever appears on the INACTIVE
    // outline state: `border-violet-500/30 text-violet-400`). The stable
    // signal of "toggled on" is the aria-pressed state the component
    // already sets, not a CSS class string.
    await expect(maBtn).toHaveAttribute('aria-pressed', 'true');
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
