/**
 * Support/Resistance price-line feature — bd:features-2026-09 slice 2.
 * Quinn Phase 3b (own-run, adversarial). See outputs/features-2026-09/03-quinn-review.md
 * for the honest execution-status breakdown of what actually ran in this
 * sandbox vs what only ran statically (--list) vs what needs the real Docker
 * stack + a real browser to prove.
 *
 * Scope covered here:
 *  1. Toggle button — hidden-state default (aria-pressed=false), visible,
 *     and flips state on click / click-again.
 *  2. sr-levels endpoint is fetched on chart load (decoration fetch, fires
 *     independently of the toggle — see useSrLevels.ts, no toggle guard).
 *  3. Empty-response and error-response resilience (no crash).
 *  4. API contract shape — real backend, `request` fixture (no page mock),
 *     same pattern as health.spec.ts.
 *
 * bd:features-2026-09 iter3 (Quinn Finding Q1 fix) — TradingChart.tsx now
 * renders a hidden `data-testid="sr-lines-count"` span that mirrors
 * `srPriceLinesRef.current.length` (updated by the same effect that calls
 * `syncSrPriceLines`, see TradingChart.tsx + utils/syncSrPriceLines.ts). The
 * "toggle count" tests below assert against that hook. This closes the
 * count/presence gap; it still does NOT prove color/position/label
 * correctness on the actual <canvas> pixels — that remains a visual-
 * regression (Percy/Chromatic) gap, tracked separately, not silently folded
 * into this count assertion.
 */
import { test, expect } from '@playwright/test';
import { mockStockAPIs, MOCK_SR_LEVELS } from './helpers/mocks';

test.describe('SR Levels toggle — button state', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/');
  });

  test('S/R toggle button is visible in the chart toolbar', async ({ page }) => {
    const toggle = page.getByRole('button', { name: 'Toggle support/resistance levels' });
    await expect(toggle).toBeVisible();
  });

  test('S/R toggle is OFF (aria-pressed=false) by default on chart load, zero lines drawn', async ({ page }) => {
    // AC: lines must not render by default. aria-pressed is the DOM signal
    // ChartToolbar.tsx wires directly to the showSrLevels boolean
    // (ChartToolbar.tsx:136); the sr-lines-count hook (TradingChart.tsx,
    // bd:features-2026-09 iter3 — Quinn Finding Q1 fix) is the actual proof
    // that zero price lines exist, not just that the button itself is off.
    const toggle = page.getByRole('button', { name: 'Toggle support/resistance levels' });
    await expect(toggle).toHaveAttribute('aria-pressed', 'false');
    // Inactive-state class per ChartToolbar.tsx:137 ternary
    await expect(toggle).toHaveClass(/btn-outline/);
    await expect(page.getByTestId('sr-lines-count')).toHaveText('0');
  });

  test('clicking the toggle flips aria-pressed to true, applies active style, and draws N lines', async ({ page }) => {
    const toggle = page.getByRole('button', { name: 'Toggle support/resistance levels' });
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-pressed', 'true');
    await expect(toggle).toHaveClass(/bg-\[var\(--color-accent-strong\)\]/);
    // MOCK_SR_LEVELS (helpers/mocks.ts) has 2 rows for the default PTT.BK
    // symbol — the count hook must match exactly, not just be "nonzero".
    await expect(page.getByTestId('sr-lines-count')).toHaveText(String(MOCK_SR_LEVELS.length));
  });

  test('clicking the toggle twice returns it to OFF and clears all lines back to zero', async ({ page }) => {
    const toggle = page.getByRole('button', { name: 'Toggle support/resistance levels' });
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-pressed', 'true');
    await expect(page.getByTestId('sr-lines-count')).toHaveText(String(MOCK_SR_LEVELS.length));
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-pressed', 'false');
    await expect(page.getByTestId('sr-lines-count')).toHaveText('0');
  });
});

test.describe('SR Levels — data fetch wiring', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
  });

  test('sr-levels endpoint is fetched on chart load even with the toggle OFF', async ({ page }) => {
    // useSrLevels.ts has no showSrLevels guard in its effect deps — it
    // fetches purely off selectedStock.sym. This test documents that as
    // current behavior (a decoration prefetch, silent per SILENT_PATHS), not
    // as an endorsement — see 03-quinn-review.md for the perf/privacy note
    // (global, unauthenticated, always-on fetch of price-annotation data).
    let srLevelsFetched = false;
    let requestedUrl = '';
    await mockStockAPIs(page);
    page.on('request', (req) => {
      if (req.url().includes('/sr-levels/')) {
        srLevelsFetched = true;
        requestedUrl = req.url();
      }
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    expect(srLevelsFetched).toBe(true);
    // Default selected stock is PTT.BK (chart.spec.ts's own baseline
    // assertion) — confirms case is preserved verbatim in the request path,
    // NOT upper/lowercased client-side (server does the .upper()).
    expect(decodeURIComponent(requestedUrl)).toContain('/sr-levels/PTT.BK');
  });

  test('empty sr-levels response does not crash the chart page', async ({ page }) => {
    await mockStockAPIs(page);
    await page.route('**/api/v1/sr-levels/*', (route) =>
      route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
    );
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    await expect(page.getByText('Watchlist', { exact: true })).toBeVisible();
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 10_000 });

    // Toggling on with zero levels must not throw / must not disable the button
    const toggle = page.getByRole('button', { name: 'Toggle support/resistance levels' });
    await toggle.click();
    await expect(toggle).toHaveAttribute('aria-pressed', 'true');
  });

  test('sr-levels network error (500) does not crash the chart page', async ({ page }) => {
    await mockStockAPIs(page);
    await page.route('**/api/v1/sr-levels/*', (route) =>
      route.fulfill({ status: 500, contentType: 'application/json', body: JSON.stringify({ detail: 'boom' }) }),
    );
    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // /sr-levels is in SILENT_PATHS (api.ts:38) — must NOT toast an error
    await expect(page.locator('canvas').first()).toBeVisible({ timeout: 10_000 });
    const toastEl = page.locator('[role="status"], .go2072408551, [class*="toast"]');
    // Best-effort: no visible error toast text referencing this failure
    await expect(page.getByText(/boom/i)).not.toBeVisible();
    void toastEl;
  });

  test('sr-levels aborted/network-failure request does not crash the chart page', async ({ page }) => {
    await mockStockAPIs(page);
    await page.route('**/api/v1/sr-levels/*', (route) => route.abort('failed'));
    await page.goto('/');
    await page.waitForLoadState('networkidle');
    await expect(page.getByText('Watchlist', { exact: true })).toBeVisible();
  });

  test('switching symbols refetches sr-levels for the new symbol', async ({ page }) => {
    const seen: string[] = [];
    await mockStockAPIs(page);
    page.on('request', (req) => {
      const m = decodeURIComponent(req.url()).match(/\/sr-levels\/([^/?]+)/);
      if (m) seen.push(m[1]);
    });

    await page.goto('/');
    await page.waitForLoadState('networkidle');

    // Click AAPL in the default guest watchlist (sidebar.spec.ts's own
    // baseline pattern for symbol switch)
    const aaplRow = page.getByRole('button').filter({ hasText: 'AAPL' }).first();
    await aaplRow.click();
    await page.waitForLoadState('networkidle');

    expect(seen).toContain('PTT.BK');
    expect(seen).toContain('AAPL');
  });
});

test.describe('SR Levels — API contract (real backend, no page mock)', () => {
  // Same pattern as health.spec.ts: hits the real backend directly via the
  // `request` fixture. Requires the Docker stack up (docker-compose.dev.yml)
  // AND a symbol with seeded sr_levels rows — NOT run in this sandbox (no
  // Docker daemon available here; see 03-quinn-review.md Execution Status).
  test('GET /api/v1/sr-levels/{symbol} returns the {data,meta} envelope', async ({ request }) => {
    const res = await request.get('/api/v1/sr-levels/PTT.BK');
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body).toHaveProperty('data');
    expect(body).toHaveProperty('meta');
    expect(Array.isArray(body.data)).toBe(true);
  });

  test('each sr-level row has the full SRLevelResponse shape', async ({ request }) => {
    const res = await request.get('/api/v1/sr-levels/PTT.BK');
    const body = await res.json();
    for (const row of body.data as unknown[]) {
      expect(row).toMatchObject({
        id: expect.any(Number),
        symbol: expect.any(String),
        price: expect.any(Number),
        level_type: expect.stringMatching(/^(support|resistance)$/),
        // bd:features-2026-09 iter3 (Chris Finding 1 fix) — 'user_created' is
        // deliberately excluded by this unauthenticated route (see
        // sr_levels.py's _PUBLIC_SOURCES); do not widen this regex back to
        // include it without also adding the auth/ownership filter Chris's
        // finding calls for.
        source: expect.stringMatching(/^(manual_import|auto_pivot)$/),
      });
      // tag / color are nullable — must be present as keys (string or null),
      // not silently dropped by the envelope's JSON round-trip
      expect(row).toHaveProperty('tag');
      expect(row).toHaveProperty('color');
    }
  });

  // Tripwire (Quinn Finding Q3, 03-quinn-review.md) — fails the moment this
  // endpoint's filter regresses and starts leaking user_created rows again,
  // independent of the shape-match test above (which would only catch it if
  // the regex were also loosened at the same time).
  test('no user_created row is ever returned by this unauthenticated endpoint', async ({ request }) => {
    const res = await request.get('/api/v1/sr-levels/PTT.BK');
    const body = await res.json();
    const sources = (body.data as Array<{ source: string }>).map((row) => row.source);
    expect(sources).not.toContain('user_created');
  });

  test('unknown symbol returns 200 with an empty data array (not 404)', async ({ request }) => {
    const res = await request.get('/api/v1/sr-levels/ZZZNOPE');
    expect(res.status()).toBe(200);
    const body = await res.json();
    expect(body.data).toEqual([]);
  });

  test('symbol is matched case-insensitively', async ({ request }) => {
    const lower = await request.get('/api/v1/sr-levels/ptt.bk');
    const upper = await request.get('/api/v1/sr-levels/PTT.BK');
    expect(lower.status()).toBe(upper.status());
    expect((await lower.json()).data.length).toEqual((await upper.json()).data.length);
  });

  test('no Authorization header is required (public read, matches stocks/* convention)', async ({ request }) => {
    const res = await request.get('/api/v1/sr-levels/PTT.BK', { headers: {} });
    expect(res.status()).not.toBe(401);
  });
});

// Documents MOCK_SR_LEVELS's own shape stays aligned with what the toggle
// tests above assume (one color-present + one color-null row, per level_type)
// — a drift here silently invalidates the "does the endpoint feed correctly
// colored rows" intent, even though DOM assertions can't check the actual
// rendered color (KNOWN GAP, file header).
test('MOCK_SR_LEVELS fixture covers both color-present and color-null rows', () => {
  const hasColor = MOCK_SR_LEVELS.some((l) => l.color !== null);
  const hasNullColor = MOCK_SR_LEVELS.some((l) => l.color === null);
  expect(hasColor).toBe(true);
  expect(hasNullColor).toBe(true);
});
