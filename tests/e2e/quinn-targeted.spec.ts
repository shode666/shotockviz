/**
 * bd:ux-2026-09 — Quinn Phase 3b targeted checks (test-only, own-run).
 *
 * Covers items the standard suite doesn't exercise:
 *  1. Watchlist add -> "loading price…" -> price after a mocked WS
 *     `data_ready` message (proves the bumpDataVersion fix end-to-end).
 *  2. RightPanel overlay open/close (desktop dock + 390px bottom-sheet),
 *     Escape-to-close, focus return to trigger.
 *  3. /settings renders with the Telegram Chat ID field.
 *  4. Mobile bottom-tab navigation to all 5 routes.
 *  5. Indicator pills render single-line (equal height, same row) at
 *     1280px and 1440px.
 *
 * Not committed as a permanent addition to the suite's coverage claim —
 * this file documents Quinn's own-run Phase 3b evidence; see
 * outputs/ux-2026-09/07-quinn-review.md for disposition.
 */
import { test, expect } from '@playwright/test';
import { mockStockAPIs, mockAuthSession, mockWatchlistAPIs, MOCK_WATCHLIST } from './helpers/mocks';

// ---------------------------------------------------------------------------
// 1. Watchlist add -> loading price -> price via mocked WS data_ready
// ---------------------------------------------------------------------------
test('watchlist row: loading -> priced, WS data_ready pushed via routeWebSocket', async ({ page }) => {
  let quotesIncludeNvda = false;
  let sendDataReady: ((msg: string) => void) | null = null;

  await mockAuthSession(page);
  await mockStockAPIs(page);
  await mockWatchlistAPIs(page, { ...MOCK_WATCHLIST, items: [{ symbol: 'PTT.BK', sort_order: 0 }] });

  await page.route('**/api/v1/stocks/quotes**', (route) => {
    const map: Record<string, unknown> = { 'PTT.BK': { price: 35.5, change: 0.5, change_pct: 1.43 } };
    if (quotesIncludeNvda) map['NVDA'] = { price: 812.34, change: 3.2, change_pct: 0.4 };
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(map) });
  });

  await page.routeWebSocket('**/api/ws/prices', (ws) => {
    sendDataReady = (msg: string) => ws.send(msg);
  });

  await page.goto('/');
  await page.waitForLoadState('networkidle');

  await page.locator('aside').locator('button').first().click();
  const input = page.locator('input[placeholder="PTT.BK, AAPL..."]');
  await input.waitFor({ state: 'visible' });
  await input.fill('NVDA');
  await expect(page.getByText('NVIDIA Corporation').first()).toBeVisible({ timeout: 5_000 });
  // MOCK_SEARCH_RESULTS is static (ignores the query string) — PTT.BK sorts
  // first and is already in MOCK_WATCHLIST's default items, so `.first()`
  // would silently re-add an existing symbol (no pending row). Target the
  // NVDA row specifically.
  await page.locator('.glass-dropdown button', { hasText: 'NVDA' }).click();

  await expect(page.locator('aside').locator('text=loading price…')).toBeVisible({ timeout: 3_000 });

  quotesIncludeNvda = true;
  expect(sendDataReady, 'WS route handler must have fired before goto resolved').not.toBeNull();
  sendDataReady!(JSON.stringify({ type: 'data_ready', data_type: 'quote', symbol: 'NVDA' }));

  await expect(page.locator('aside').locator('text=loading price…')).not.toBeVisible({ timeout: 5_000 });
  await expect(page.locator('aside').getByText('812.34')).toBeVisible({ timeout: 3_000 });
});

// ---------------------------------------------------------------------------
// 2. RightPanel overlay — desktop dock, mobile bottom-sheet, Escape, focus
// ---------------------------------------------------------------------------
test.describe('RightPanel overlay', () => {
  test.beforeEach(async ({ page }) => {
    await mockStockAPIs(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('desktop (1280px): opens docked right, closes via X button', async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 900 });
    const toggle = page.getByRole('button', { name: 'เปิดแผงข้อมูล' });
    await toggle.click();

    const panel = page.locator('aside[aria-label="รายละเอียดหุ้น"]');
    await expect(panel).toBeVisible();
    const box = await panel.boundingBox();
    expect(box).not.toBeNull();
    // Docked to the right edge, ~260px wide per RightPanel.tsx md:w-[260px]
    expect(box!.x + box!.width).toBeGreaterThan(1270);
    expect(box!.width).toBeLessThan(300);

    // Scoped to the panel: the outer toggle button's aria-label also flips to
    // "ปิดแผงข้อมูล" while open (bd:ux-2026-09 Q-UX1 fix-verify — now that the
    // toggle is actually clickable, the unscoped locator collides with it).
    const closeBtn = panel.getByRole('button', { name: 'ปิดแผงข้อมูล' });
    await closeBtn.click();
    // Closed panel is `inert` (removed from a11y tree) — check the attribute
    // directly rather than visibility (transform-based, still painted mid-transition).
    await expect(panel).toHaveJSProperty('inert', true, { timeout: 3_000 });
  });

  test('desktop (1440px): opens docked right, closes via X button', async ({ page }) => {
    // bd:ux-2026-09 Quinn Q-UX1 fix-verify — toggle button sat behind the
    // lightweight-charts price-axis <canvas> (z-index: 2, button had none)
    // at every width; 1440 is Oliver's 3rd required breakpoint (1280 + 390
    // already covered above).
    await page.setViewportSize({ width: 1440, height: 900 });
    const toggle = page.getByRole('button', { name: 'เปิดแผงข้อมูล' });
    await toggle.click();

    const panel = page.locator('aside[aria-label="รายละเอียดหุ้น"]');
    await expect(panel).toBeVisible();
    const box = await panel.boundingBox();
    expect(box).not.toBeNull();
    expect(box!.x + box!.width).toBeGreaterThan(1430);
    expect(box!.width).toBeLessThan(300);

    const closeBtn = panel.getByRole('button', { name: 'ปิดแผงข้อมูล' });
    await closeBtn.click();
    await expect(panel).toHaveJSProperty('inert', true, { timeout: 3_000 });
  });

  test('mobile (390px): opens as bottom-sheet, backdrop click closes', async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    const toggle = page.getByRole('button', { name: 'เปิดแผงข้อมูล' });
    await toggle.click();

    const panel = page.locator('aside[aria-label="รายละเอียดหุ้น"]');
    await expect(panel).toBeVisible();
    const box = await panel.boundingBox();
    expect(box).not.toBeNull();
    // Bottom-sheet: full viewport width, anchored to bottom
    expect(box!.width).toBeGreaterThan(380);
    expect(box!.y + box!.height).toBeGreaterThan(800);

    // Backdrop is the mobile-only `md:hidden` div — click it, not the panel.
    await page.mouse.click(10, 10);
    await expect(panel).toHaveJSProperty('inert', true, { timeout: 3_000 });
  });

  test('Escape key closes the panel', async ({ page }) => {
    // bd:ux-2026-09 Chris review (Q-UX2) fix-verify — RightPanel.tsx now has
    // a keydown/Escape handler (pattern: SearchModal.tsx:163).
    await page.setViewportSize({ width: 1280, height: 900 });
    const toggle = page.getByRole('button', { name: 'เปิดแผงข้อมูล' });
    await toggle.click();
    const panel = page.locator('aside[aria-label="รายละเอียดหุ้น"]');
    await expect(panel).toBeVisible();

    await page.keyboard.press('Escape');
    await expect(panel).toHaveJSProperty('inert', true, { timeout: 2_000 });
  });

  test('focus returns to trigger button after close', async ({ page }) => {
    // bd:ux-2026-09 Chris review (Q-UX2) fix-verify — ChartPage's closeRightPanel
    // now explicitly refocuses the toggle button (rightPanelToggleRef) instead
    // of letting the just-clicked close button go `inert` and drop focus to
    // document.body.
    await page.setViewportSize({ width: 1280, height: 900 });
    const toggle = page.getByRole('button', { name: 'เปิดแผงข้อมูล' });
    await toggle.click();
    const panel = page.locator('aside[aria-label="รายละเอียดหุ้น"]');
    const closeBtn = panel.getByRole('button', { name: 'ปิดแผงข้อมูล' });
    await closeBtn.click();

    await expect(page.getByRole('button', { name: 'เปิดแผงข้อมูล' })).toBeFocused({ timeout: 2_000 });
  });
});

// ---------------------------------------------------------------------------
// 3. /settings renders with Telegram field
// ---------------------------------------------------------------------------
test('/settings renders with Telegram Chat ID field', async ({ page }) => {
  await mockAuthSession(page);
  await mockStockAPIs(page);
  await page.goto('/settings');
  await page.waitForLoadState('networkidle');

  await expect(page.getByText('Telegram Chat ID')).toBeVisible();
  const telegramInput = page.locator('#settings-telegram');
  await expect(telegramInput).toBeVisible();
  await expect(page.locator('label[for="settings-telegram"]')).toBeVisible();
});

// ---------------------------------------------------------------------------
// 4. Mobile bottom-tab navigation — all 5 routes
// ---------------------------------------------------------------------------
test('mobile bottom-tab bar navigates to all 5 routes', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await mockAuthSession(page);
  await mockStockAPIs(page);
  await mockWatchlistAPIs(page);
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  const nav = page.locator('nav[aria-label="เมนูล่าง"]');
  await expect(nav).toBeVisible();

  const routes: Array<[string, string]> = [
    ['Dashboard', '/dashboard'],
    ['Screener', '/screener'],
    ['Portfolio', '/portfolio'],
    ['Alerts', '/alerts'],
    ['Chart', '/'],
  ];

  for (const [label, path] of routes) {
    await nav.getByText(label, { exact: true }).click();
    await page.waitForURL((url) => url.pathname === path, { timeout: 5_000 });
    expect(new URL(page.url()).pathname).toBe(path);
  }
});

// ---------------------------------------------------------------------------
// 5. Indicator pills single-line at 1280px and 1440px
// ---------------------------------------------------------------------------
test.describe('Indicator pills — single line, no wrap', () => {
  const INDICATORS = ['Volume', 'MA 20', 'EMA 50', 'RSI 14', 'VWAP', 'MACD', 'BB'];

  for (const width of [1280, 1440]) {
    test(`pills share one row + equal height at ${width}px`, async ({ page }) => {
      await page.setViewportSize({ width, height: 900 });
      await mockStockAPIs(page);
      await page.goto('/');
      await page.waitForLoadState('networkidle');

      const heights: number[] = [];
      const tops: number[] = [];
      for (const ind of INDICATORS) {
        const pill = page.getByRole('button', { name: ind, exact: true });
        await expect(pill).toBeVisible({ timeout: 5_000 });
        const box = await pill.boundingBox();
        expect(box).not.toBeNull();
        heights.push(box!.height);
        tops.push(Math.round(box!.y));
      }
      const uniqueHeights = new Set(heights.map((h) => Math.round(h)));
      const uniqueTops = new Set(tops);
      expect(uniqueHeights.size, `pill heights differ: ${heights.join(',')}`).toBe(1);
      expect(uniqueTops.size, `pills not on same row (top y): ${tops.join(',')}`).toBe(1);
    });
  }
});
