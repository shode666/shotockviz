/**
 * Playwright API mock helpers
 *
 * Usage:
 *   import { mockStockAPIs } from './helpers/mocks';
 *   test.beforeEach(async ({ page }) => { await mockStockAPIs(page); });
 */
import type { Page } from '@playwright/test';

// ---------------------------------------------------------------------------
// Sample data
// ---------------------------------------------------------------------------

export const MOCK_QUOTE = {
  price: 35.5,
  change: 0.5,
  change_pct: 1.43,
  open: 35.0,
  high: 36.2,
  low: 34.8,
  volume: 1_500_000,
};

export const MOCK_BARS = Array.from({ length: 10 }, (_, i) => ({
  time: `2024-01-${String(i + 1).padStart(2, '0')}`,
  open: 34 + i * 0.3,
  high: 35 + i * 0.3,
  low: 33 + i * 0.3,
  close: 34.5 + i * 0.3,
  volume: 1_000_000 + i * 50_000,
}));

/**
 * IMPORTANT: history response must wrap bars in {symbol, timeframe, bars:[...]}
 * to match the StockHistory schema. Frontend reads data.bars — not data directly.
 */
export const MOCK_HISTORY = {
  symbol: 'PTT.BK',
  timeframe: '1D',
  bars: MOCK_BARS,
};

export const MOCK_SCREENER_RESULTS = [
  {
    sym: 'AAPL',
    name: 'Apple Inc.',
    rsi: 28.4,
    macd: 'Buy',
    vol: '2.3x',
    price: '187.42',
    chg: '+1.5%',
    up: true,
    signal: 'Strong Buy',
  },
  {
    sym: 'NVDA',
    name: 'NVIDIA Corp.',
    rsi: 29.1,
    macd: 'Buy',
    vol: '2.1x',
    price: '824.15',
    chg: '+2.1%',
    up: true,
    signal: 'Strong Buy',
  },
];

export const MOCK_AUTH_ME = {
  id: 1,
  email: 'test@example.com',
  display_name: 'Test User',
  role: 'user',
  created_at: '2024-01-01T00:00:00Z',
};

export const MOCK_WATCHLIST = {
  id: 1,
  name: 'My Watchlist',
  sort_order: 0,
  items: [
    { symbol: 'PTT.BK', sort_order: 0 },
    { symbol: 'AAPL', sort_order: 1 },
  ],
};

/**
 * bd:features-2026-09 slice 2 (Quinn Phase 3b) — SR levels for PTT.BK.
 * Deliberately covers both color-present and color-null (fallback) rows,
 * one of each level_type, matching srLevelColor.test.ts's coverage.
 */
export const MOCK_SR_LEVELS = [
  { id: 1, symbol: 'PTT.BK', price: 33.0, level_type: 'support', tag: 'S1', color: '#fde047', source: 'manual_import' },
  { id: 2, symbol: 'PTT.BK', price: 38.0, level_type: 'resistance', tag: null, color: null, source: 'auto_pivot' },
];

export const MOCK_SEARCH_RESULTS = [
  { symbol: 'PTT.BK', name: 'PTT Public Company', name_th: 'ปตท.', market: 'SET' },
  { symbol: 'AAPL', name: 'Apple Inc.', name_th: null, market: 'US' },
  { symbol: 'NVDA', name: 'NVIDIA Corporation', name_th: null, market: 'US' },
];

// ---------------------------------------------------------------------------
// Route interceptors
// ---------------------------------------------------------------------------

/**
 * Mock all stock data endpoints (quote, history, search, fundamentals, names).
 * Call in beforeEach — no real network traffic.
 */
export async function mockStockAPIs(page: Page): Promise<void> {
  // bd:ux-2026-09 (Quinn, test-only) — this sandbox transparently
  // intercepts ALL outbound :443 traffic by SNI regardless of destination
  // IP (confirmed: even --host-resolver-rules pointing these hosts at
  // 127.0.0.1 still hangs ~6-8s per request via the agent proxy). Abort
  // at the Playwright network-interception layer instead (CDP, before any
  // socket opens) so Google Fonts preconnect/stylesheet + GSI script
  // requests fail in ~10ms instead of paying a multi-second tax on every
  // single test.
  await page.route(/fonts\.(googleapis|gstatic)\.com|accounts\.google\.com/, (route) => route.abort());

  // Quote — 200 with price data
  await page.route('**/api/v1/stocks/*/quote', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_QUOTE),
    }),
  );

  // History — wraps bars in {symbol, timeframe, bars:[...]} to match StockHistory schema
  await page.route('**/api/v1/stocks/*/history**', (route) => {
    const url = new URL(route.request().url());
    const tf = url.searchParams.get('tf') ?? '1D';
    const symMatch = route.request().url().match(/\/stocks\/([^/]+)\/history/);
    const sym = symMatch ? decodeURIComponent(symMatch[1]).toUpperCase() : 'PTT.BK';
    return route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ symbol: sym, timeframe: tf, bars: MOCK_BARS }),
    });
  });

  // Fundamentals — matches backend StockFundamentals schema keys
  await page.route('**/api/v1/stocks/*/fundamentals', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        symbol: 'PTT.BK',
        pe_ratio: 28.5,
        eps: 6.43,
        market_cap: 2_900_000_000_000,
        dividend_yield: 0.52,
        pb_ratio: 3.2,
      }),
    }),
  );

  // News
  await page.route('**/api/v1/stocks/*/news', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { title: 'Test news item', url: 'https://example.com/1', source: 'Test', published_at: '2024-01-01', summary: 'Test summary' },
      ]),
    }),
  );

  // Batch names lookup — returns {symbol: displayName} map
  await page.route('**/api/v1/stocks/names**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ 'PTT.BK': 'ปตท.', AAPL: 'Apple Inc.', NVDA: 'NVIDIA', '^SET': 'SET Index', '^GSPC': 'S&P 500', '^IXIC': 'NASDAQ' }),
    }),
  );

  // Stock search
  await page.route('**/api/v1/stocks/search**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_SEARCH_RESULTS),
    }),
  );

  // Watchlist — 401 for unauthenticated guests
  await page.route('**/api/v1/watchlists**', (route) =>
    route.fulfill({ status: 401, body: JSON.stringify({ detail: 'Not authenticated' }) }),
  );

  // System ready
  await page.route('**/api/v1/system/ready', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ready: true }) }),
  );

  // SR levels — bd:features-2026-09 slice 2 (Quinn Phase 3b). Fires on every
  // chart-page load (useSrLevels.ts has no toggle guard — it fetches
  // regardless of showSrLevels), so this default handler is required to keep
  // every OTHER spec in this suite deterministic now that TradingChart.tsx
  // always calls it. Dave's PR did not add this default (not listed in his
  // Files Changed for tests/e2e/) — flagged in 03-quinn-review.md.
  await page.route('**/api/v1/sr-levels/*', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(MOCK_SR_LEVELS),
    }),
  );
}

/**
 * Mock the screener endpoint with configurable result set.
 */
export async function mockScreener(
  page: Page,
  results = MOCK_SCREENER_RESULTS,
): Promise<void> {
  await page.route('**/api/v1/screener**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(results),
    }),
  );
}

/**
 * Mock /api/v1/auth/me to simulate an authenticated session.
 * Call BEFORE page.goto() so the token check on mount resolves correctly.
 */
export async function mockAuthSession(page: Page, user = MOCK_AUTH_ME): Promise<void> {
  await page.addInitScript(() => {
    localStorage.setItem('access_token', 'mock-access-token');
    localStorage.setItem('refresh_token', 'mock-refresh-token');
  });

  await page.route('**/api/v1/auth/me', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(user),
    }),
  );
}

/**
 * Mock watchlist CRUD endpoints for authenticated users.
 * Removes the default 401 handler set by mockStockAPIs before registering
 * authenticated routes (Playwright routes match FIFO — first registered wins).
 * Call after mockAuthSession and mockStockAPIs.
 */
export async function mockWatchlistAPIs(
  page: Page,
  watchlist = MOCK_WATCHLIST,
): Promise<void> {
  // Remove the 401 catch-all added by mockStockAPIs so our handlers take effect
  await page.unroute('**/api/v1/watchlists**');

  // GET /api/v1/watchlists
  await page.route('**/api/v1/watchlists', (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify([watchlist]),
      });
    }
    // POST /api/v1/watchlists — create
    if (route.request().method() === 'POST') {
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({ id: 2, name: 'My Watchlist', sort_order: 0, items: [] }),
      });
    }
    return route.continue();
  });

  // POST /api/v1/watchlists/:id/stocks — add stock
  await page.route('**/api/v1/watchlists/*/stocks', (route) => {
    if (route.request().method() === 'POST') {
      return route.fulfill({
        status: 201,
        contentType: 'application/json',
        body: JSON.stringify({ message: 'Stock added' }),
      });
    }
    // PATCH reorder (url ends in /stocks/reorder)
    if (route.request().method() === 'PATCH') {
      return route.fulfill({ status: 204, body: '' });
    }
    return route.continue();
  });

  // DELETE /api/v1/watchlists/:id/stocks/:symbol
  await page.route('**/api/v1/watchlists/*/stocks/*', (route) => {
    if (route.request().method() === 'DELETE') {
      return route.fulfill({ status: 204, body: '' });
    }
    return route.continue();
  });
}
