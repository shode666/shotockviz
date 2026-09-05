/**
 * bd:ui-honesty-2026-09 — Quinn Phase 3b E2E regression coverage.
 *
 * Bella's spec (outputs/ui-honesty-2026-09/03-bella-spec.md) ships F1-F12 with
 * zero automated E2E behind most of them — Oliver's 20-verify.md Phase 3a is a
 * one-off manual browser check (12/12 PASS) that will not catch a future
 * regression. This file locks down the highest-value, most regression-prone
 * ACs: the ones with real conditional logic (F6, F7, F11) or a real backend
 * round-trip (F8, F9), not the pure-JSX removals (F1 gets one cheap smoke
 * check; F2/F4/F12 are adequately covered by unit tests per Bella's spec and
 * are not re-covered here — see 31-quinn-review.md §2).
 *
 * Own-run, all specs pass against the live dev stack (https://localhost) at
 * the time this file was written — see 31-quinn-review.md for the full
 * command + output.
 */
import { test, expect } from '@playwright/test';
import { mockStockAPIs, mockAuthSession, mockWatchlistAPIs, mockScreener, MOCK_AUTH_ME, MOCK_SCREENER_RESULTS } from './helpers/mocks';

// NOTE (own finding, not part of Bella's F1-F12 scope but required to make
// these specs reliable): mockStockAPIs() stubs `**/api/v1/watchlists**` with
// an unconditional 401 (meant for guest tests). api.ts's global response
// interceptor treats ANY 401 — from ANY endpoint — as "session invalid" and
// clears the session (ADR-007, api.ts:44-45, "reuses authStore's existing
// 401-cleanup on ANY 401 response so One Tap unblocks immediately"). Every
// authenticated test in this file therefore MUST call mockWatchlistAPIs()
// right after mockAuthSession(), or Sidebar's authenticated watchlist fetch
// silently logs the mocked session back out mid-test. See
// 31-quinn-review.md §1 for the write-up (this cost real debugging time —
// flagged so the next author doesn't repeat it).

// ---------------------------------------------------------------------------
// F1 — Drawing toolbar removed (cheap smoke check; the removal itself has no
// logic worth a heavier test, but a future re-import regression is realistic
// — ChartPage.tsx re-adding `<DrawingToolbar />` would not fail build/tsc).
// ---------------------------------------------------------------------------
test('F1: no "Drawing:" toolbar renders above/below the chart', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
  });
  await mockStockAPIs(page);
  await page.goto('/');
  await page.waitForLoadState('networkidle');

  await expect(page.getByText(/Drawing:/)).toHaveCount(0);
});

// ---------------------------------------------------------------------------
// F5 — VWAP pill disabled on daily+ timeframes, re-enables on intraday.
// ---------------------------------------------------------------------------
test.describe('F5: VWAP pill intraday-only', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/');
    await page.waitForLoadState('networkidle');
  });

  test('1D (default): VWAP pill is disabled with an explanatory title', async ({ page }) => {
    const vwap = page.getByRole('button', { name: 'VWAP', exact: true });
    await expect(vwap).toBeVisible();
    await expect(vwap).toBeDisabled();
    await expect(vwap).toHaveAttribute('aria-disabled', 'true');
    await expect(vwap).toHaveAttribute('title', 'VWAP is intraday-only');
  });

  test('switching to 1h re-enables the VWAP pill', async ({ page }) => {
    await page.getByRole('button', { name: '1h', exact: true }).click();
    const vwap = page.getByRole('button', { name: 'VWAP', exact: true });
    await expect(vwap).toBeEnabled();
    await expect(vwap).toHaveAttribute('aria-disabled', 'false');
    await expect(vwap).toHaveAttribute('title', 'VWAP');
  });
});

// ---------------------------------------------------------------------------
// F6 — Guest watchlist: clicking a row must show the SAME real price the row
// itself displays, not a '—' placeholder. This is the exact iter1 bug (Sidebar
// render path read one source, click handler read another) — the highest
// regression-risk item in this bd because it silently reintroduces itself if
// either path is edited independently in the future.
// ---------------------------------------------------------------------------
test('F6: guest clicking a watchlist row shows real price, not "—" (regression: Sidebar.tsx handleSelect must read the same source as the row render)', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
  });
  await mockStockAPIs(page);

  // Guests poll indices + GUEST_SYMBOLS through the same batch endpoint
  // (Sidebar.tsx:110-117) — mock it deterministically instead of hitting
  // real yfinance/Finnhub.
  await page.route('**/api/v1/stocks/quotes**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        AAPL: { price: 319.97, change: -7.67, change_pct: -2.34 },
        '^SET': { price: 1234.5, change: 1.2, change_pct: 0.1 },
        '^GSPC': { price: 5000, change: -10, change_pct: -0.2 },
        '^IXIC': { price: 16000, change: 50, change_pct: 0.3 },
      }),
    }),
  );

  await page.goto('/');
  await page.waitForLoadState('networkidle');

  // Row itself must show the real price (render path — already covered
  // indirectly elsewhere, asserted here so a future break shows up at the
  // row AND the click in the same test run). Scoped to the Sidebar's own
  // <aside> — the navbar's search-bar button also literally renders the text
  // "AAPL" as its placeholder example ("ค้นหา PTT, AAPL..."), which an
  // unscoped page-wide `hasText: 'AAPL'` filter would match FIRST (it's
  // earlier in DOM order than the sidebar), silently clicking the wrong
  // element.
  const sidebar = page.locator('aside').first();
  const aaplRow = sidebar.getByRole('button').filter({ hasText: 'AAPL' }).first();
  await expect(aaplRow).toBeVisible({ timeout: 8_000 });
  await expect(aaplRow.getByText('319.97')).toBeVisible();

  await aaplRow.click();

  // Toolbar header (ChartToolbar.tsx:24-49) reflects selectedStock — must be
  // the real price, never the '—' placeholder a guest used to get on click.
  // Scoped to the toolbar itself (`.panel.border-b`, StatusBar.tsx's sibling
  // pattern `.panel.border-t` is the same convention) — other unmocked
  // guest/indices symbols legitimately still show '—' elsewhere on the page,
  // that's not what this assertion is about.
  const toolbar = page.locator('div.panel.border-b').first();
  await expect(toolbar.getByText('AAPL', { exact: true })).toBeVisible();
  await expect(toolbar.getByText('319.97')).toBeVisible();
  await expect(toolbar.getByText('—', { exact: true })).toHaveCount(0);
});

// ---------------------------------------------------------------------------
// F7 — Inline form validation replaces the old silent no-op on empty submit.
// ---------------------------------------------------------------------------
test('F7: Create Alert — empty submit shows inline errors, modal does not silently close', async ({ page }) => {
  await mockStockAPIs(page);
  await mockAuthSession(page, MOCK_AUTH_ME);
  await mockWatchlistAPIs(page);
  await page.route('**/api/v1/alerts**', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) }),
  );
  await page.goto('/alerts');
  await page.waitForLoadState('networkidle');

  await page.getByRole('button', { name: 'สร้าง Alert' }).first().click();
  const modal = page.locator('.glass-panel').first();
  await expect(modal).toBeVisible();

  // Submit with symbol + value both empty (EMPTY_FORM default).
  await modal.getByRole('button', { name: 'สร้าง Alert' }).click();

  await expect(modal.getByRole('alert').filter({ hasText: 'กรุณาระบุ symbol' })).toBeVisible();
  await expect(modal.getByRole('alert').filter({ hasText: 'กรุณาระบุค่า' })).toBeVisible();
  // Not a silent no-op: modal is still open, not dismissed.
  await expect(modal).toBeVisible();
});

test('F7: Add Transaction — empty submit shows inline errors, modal does not silently close', async ({ page }) => {
  await mockStockAPIs(page);
  await mockAuthSession(page, MOCK_AUTH_ME);
  await mockWatchlistAPIs(page);
  await page.route('**/api/v1/portfolio/analytics**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        total_value: 100000, total_cost: 90000, unrealized_pl: 10000,
        unrealized_pl_pct: 11.1, has_pending_prices: false, holdings: [],
      }),
    }),
  );
  await page.route('**/api/v1/portfolio', (route) => {
    if (route.request().method() === 'GET') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
    }
    return route.continue();
  });

  await page.goto('/portfolio');
  await page.waitForLoadState('networkidle');

  await page.getByRole('button', { name: '+ เพิ่มธุรกรรม' }).click();
  const modal = page.locator('.glass-panel').first();
  await expect(modal).toBeVisible();

  await modal.getByRole('button', { name: 'บันทึก' }).click();

  await expect(modal.getByRole('alert').filter({ hasText: 'กรุณาระบุ symbol' })).toBeVisible();
  await expect(modal.getByRole('alert').filter({ hasText: 'กรุณาระบุจำนวน' })).toBeVisible();
  await expect(modal.getByRole('alert').filter({ hasText: 'กรุณาระบุราคา' })).toBeVisible();
  await expect(modal).toBeVisible();
});

// ---------------------------------------------------------------------------
// F8 — Notes delete: real DELETE round-trip + textarea clears.
// ---------------------------------------------------------------------------
test('F8: RightPanel Notes — delete clears the note and calls DELETE /notes/{symbol}', async ({ page }) => {
  await mockStockAPIs(page);
  await mockAuthSession(page, MOCK_AUTH_ME);
  await mockWatchlistAPIs(page);

  let deleteCalled = false;
  await page.route('**/api/v1/notes/*', (route) => {
    const method = route.request().method();
    if (method === 'GET') {
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ content: 'existing note text' }),
      });
    }
    if (method === 'DELETE') {
      deleteCalled = true;
      return route.fulfill({ status: 204, body: '' });
    }
    return route.continue();
  });

  page.on('dialog', (d) => d.accept());

  await page.goto('/');
  await page.waitForLoadState('networkidle');

  await page.getByRole('button', { name: 'เปิดแผงข้อมูล' }).click();
  const panel = page.locator('aside[aria-label="รายละเอียดหุ้น"]');
  await expect(panel).toBeVisible();

  await panel.getByRole('button', { name: 'Notes' }).click();
  const textarea = panel.locator('textarea');
  await expect(textarea).toHaveValue('existing note text');

  const deleteBtn = panel.getByRole('button', { name: 'ลบบันทึก' });
  await expect(deleteBtn).toBeEnabled();
  await deleteBtn.click();

  await expect(textarea).toHaveValue('');
  expect(deleteCalled, 'DELETE /notes/{symbol} must have fired').toBe(true);
  await expect(deleteBtn).toBeDisabled();
});

// ---------------------------------------------------------------------------
// F9 — Screener: Save Filter gone, Export CSV produces a real download with
// the correct header + escaped rows (resultsToCsv).
// ---------------------------------------------------------------------------
test.describe('F9: Screener honesty', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
  });

  test('Save Filter button is gone', async ({ page }) => {
    await page.goto('/screener');
    await expect(page.getByRole('button', { name: /Save Filter/ })).toHaveCount(0);
  });

  test('Export CSV is disabled with zero results, enabled + downloads after Run Screen', async ({ page }) => {
    await mockScreener(page, MOCK_SCREENER_RESULTS);
    await page.goto('/screener');

    const exportBtn = page.getByRole('button', { name: /Export CSV/ });
    await expect(exportBtn).toBeDisabled();

    await page.getByRole('button', { name: /Run Screen/ }).click();
    await expect(page.getByText(`ผลลัพธ์ ${MOCK_SCREENER_RESULTS.length} หุ้น`)).toBeVisible();
    await expect(exportBtn).toBeEnabled();

    const downloadPromise = page.waitForEvent('download');
    await exportBtn.click();
    const download = await downloadPromise;

    expect(download.suggestedFilename()).toMatch(/^screener-results-\d{4}-\d{2}-\d{2}\.csv$/);
    const stream = await download.createReadStream();
    const chunks: Buffer[] = [];
    for await (const chunk of stream) chunks.push(chunk as Buffer);
    const csv = Buffer.concat(chunks).toString('utf-8');

    // bd:ui-honesty-2026-09 iter3 (Chris Medium #3): ScreenerPage.tsx now
    // prepends a UTF-8 BOM to the Blob so Excel-on-Windows doesn't mojibake
    // the Thai headers — resultsToCsv() itself is unchanged (BOM deliberately
    // kept out of the pure fn). Prove the BOM is actually there (that IS the
    // fix), not just strip it and re-assert the old string.
    const rawBytes = Buffer.concat(chunks);
    expect(rawBytes.subarray(0, 3), 'file must start with the UTF-8 BOM (EF BB BF)').toEqual(
      Buffer.from([0xef, 0xbb, 0xbf]),
    );
    // Decoding UTF-8 BOM bytes yields a leading U+FEFF character in the
    // string — confirm it round-trips through decoding too, not just at the
    // byte level, then strip it before line-splitting to check the header.
    expect(csv.charCodeAt(0), 'decoded string must start with U+FEFF').toBe(0xfeff);
    const lines = csv.slice(1).split('\r\n');
    expect(lines[0]).toBe('Symbol,ชื่อบริษัท,ราคา,เปลี่ยนแปลง,RSI,MACD,Volume,Signal');
    expect(lines[1]).toBe('AAPL,Apple Inc.,187.42,+1.5%,28.4,Buy,2.3x,Strong Buy');
    expect(lines[2]).toBe('NVDA,NVIDIA Corp.,824.15,+2.1%,29.1,Buy,2.1x,Strong Buy');
  });
});

// ---------------------------------------------------------------------------
// F10 — News with no url renders as a non-interactive element, not a dead
// `#`/`undefined` link. Covers both NewsPage and RightPanel's News tab.
//
// bd:ui-honesty-2026-09 iter3 (Oliver reject of the original `role`/
// `aria-disabled` approach): a widget role/`aria-disabled` on a bare,
// non-focusable `<div>` is itself an ARIA violation (a screen reader
// announced "link, unavailable" for something that is neither a link nor
// focusable). The product dropped `role`/`aria-disabled` entirely and now
// exposes the no-link state via `<span className="sr-only">ไม่มีลิงก์บทความ
// </span>` instead. Re-anchored on the real, intended contract: NOT an
// anchor, no `href`, and the sr-only text is present — not the removed
// attribute.
// ---------------------------------------------------------------------------
const NEWS_NO_URL = [
  { title: 'No-url news item', url: null, source: 'Test', published_at: '2024-01-01', summary: 'x' },
];

test('F10: NewsPage — item with no url is a non-interactive element with sr-only "no article link" text, not a dead "#" link', async ({ page }) => {
  await page.addInitScript(() => {
    localStorage.removeItem('access_token');
    localStorage.removeItem('refresh_token');
  });
  await mockStockAPIs(page);
  await page.route('**/api/v1/stocks/*/news', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(NEWS_NO_URL) }),
  );

  await page.goto('/news');
  await page.waitForLoadState('networkidle');

  // NewsCard's url-less branch is the only element on this page carrying
  // both the "panel" class and the injected title text — unambiguous.
  const card = page.locator('div.panel').filter({ hasText: 'No-url news item' });
  await expect(card).toBeVisible();
  await expect(card).toHaveJSProperty('tagName', 'DIV');
  await expect(card).not.toHaveAttribute('href');
  await expect(card.getByText('ไม่มีลิงก์บทความ')).toBeAttached();

  // No dead link anywhere on the page, and the title text is not inside an
  // <a> at all (not just "not href=#" — confirms it isn't a link rendered
  // with some other placeholder href either).
  await expect(page.locator('a[href="#"]')).toHaveCount(0);
  await expect(page.locator('a').filter({ hasText: 'No-url news item' })).toHaveCount(0);
});

test('F10: RightPanel News tab — item with no url is a non-interactive element with sr-only "no article link" text', async ({ page }) => {
  await mockStockAPIs(page);
  await page.route('**/api/v1/stocks/*/news', (route) =>
    route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(NEWS_NO_URL) }),
  );

  await page.goto('/');
  await page.waitForLoadState('networkidle');
  await page.getByRole('button', { name: 'เปิดแผงข้อมูล' }).click();
  const panel = page.locator('aside[aria-label="รายละเอียดหุ้น"]');
  await panel.getByRole('button', { name: 'News' }).click();

  // RightPanel's url-less item has no distinguishing class like "panel" —
  // it's a bare <div> with no sibling <div>s inside it, so the innermost
  // ("last" in document order) <div> containing the title text is the item
  // itself, not an ancestor wrapper.
  const card = panel.locator('div').filter({ hasText: 'No-url news item' }).last();
  await expect(card).toBeVisible();
  await expect(card).toHaveJSProperty('tagName', 'DIV');
  await expect(card).not.toHaveAttribute('href');
  await expect(card.getByText('ไม่มีลิงก์บทความ')).toBeAttached();

  await expect(page.locator('a[href="undefined"]')).toHaveCount(0);
  await expect(panel.locator('a').filter({ hasText: 'No-url news item' })).toHaveCount(0);
});

// ---------------------------------------------------------------------------
// F11 — superseded by bd:shotockviz-43x (commit 1eb7fee). `AlertStatus.EXPIRED`
// was struck from the backend enum, `utils/alertStatus.ts`'s mapping, and
// REQUIREMENTS.md — [backend/models/alert.py:27-41]: it was declared but
// never assigned by any code path (`grep -rn EXPIRED backend/` only found the
// enum member itself), so "resolve by striking, not by implementing"
// (Oliver/Tara). That state cannot exist on the wire any more, so the old
// "seed an EXPIRED alert, assert หมดอายุ" test is asserting on a dead code
// path. Replaced with coverage of the three statuses `getAlertStatusKey`
// actually produces [frontend/src/utils/alertStatus.ts:11-16]: `status ===
// 'TRIGGERED'` wins regardless of `is_active`; otherwise `is_active` alone
// decides active vs inactive (paused) — `status` itself is not read for that
// branch. Also guards that "หมดอายุ" does not silently reappear.
//
// Note (not this test's scope): `AlertStatus.INACTIVE` has the same
// declared-never-assigned defect and is filed separately (bd:shotockviz-o0b)
// — the UI's paused state ("หยุดชั่วคราว") comes from the `is_active` boolean,
// not from `status`, so that dead enum member doesn't affect this test.
// ---------------------------------------------------------------------------
test('F11: alert statuses render distinctly — active/triggered/inactive; EXPIRED is gone (bd:shotockviz-43x)', async ({ page }) => {
  await mockStockAPIs(page);
  await mockAuthSession(page, MOCK_AUTH_ME);
  await mockWatchlistAPIs(page);
  await page.route('**/api/v1/alerts**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        // status === 'TRIGGERED' -> 'triggered', regardless of is_active.
        { id: 1, symbol: 'PTT.BK', alert_type: 'Price Above', condition: 'above', value: 40, channel: 'in_app', status: 'ACTIVE', is_active: true },
        { id: 2, symbol: 'AAPL', alert_type: 'Price Below', condition: 'below', value: 170, channel: 'in_app', status: 'TRIGGERED', is_active: true, triggered_at: '2024-01-01T09:30:00Z' },
        // status: null + is_active: false -> 'inactive' (not read from status).
        { id: 3, symbol: 'MSFT', alert_type: 'Price Above', condition: 'above', value: 300, channel: 'in_app', status: null, is_active: false },
      ]),
    }),
  );

  await page.goto('/alerts');
  await page.waitForLoadState('networkidle');

  await expect(page.getByText('ทำงานอยู่')).toBeVisible({ timeout: 8_000 }); // active
  await expect(page.getByText('แจ้งแล้ว')).toBeVisible(); // triggered
  await expect(page.getByText('หยุดชั่วคราว')).toBeVisible(); // inactive (paused)

  // Distinct elements, not the same text rendered twice, and the dead
  // 'expired' key must not have quietly come back.
  expect(await page.getByText('ทำงานอยู่').count()).toBeGreaterThan(0);
  expect(await page.getByText('แจ้งแล้ว').count()).toBeGreaterThan(0);
  expect(await page.getByText('หยุดชั่วคราว').count()).toBeGreaterThan(0);
  await expect(page.getByText('หมดอายุ')).toHaveCount(0);
});

// ---------------------------------------------------------------------------
// F3 — superseded by bd:shotockviz-09j (commit 0b7e47b). The data_ready-driven
// label is GONE: `formatLastUpdate`, `getLastQuoteTimestamp` and
// `nextLastUpdate` were deleted from `utils/statusBar.ts` — verified directly
// against the source [frontend/src/utils/statusBar.ts:1-16], which documents
// WHY: `data_ready` with `data_type:"quote"` only fires from the Celery-outage
// fallback, so the old label read "—" under normal healthy operation. The old
// AC3/AC4 regression tests below were pinning that now-deleted concept and a
// wording ("อัปเดตล่าสุด:") that no longer exists.
//
// New contract [frontend/src/utils/statusBar.ts:18-115,
// frontend/src/components/common/StatusBar.tsx:22-65]:
//   - label renders as `ราคา {sym}: {label}` (no "อัปเดตล่าสุด:" wording)
//   - `getPriceFreshness(tsSeconds, nowMs, marketOpen)` derives age from the
//     server `ts` on the quote payload (`usePriceUpdates`), NOT from WS
//     data_ready — `dataReadyPayload` is untouched but StatusBar no longer
//     reads it
//   - amber (`stale`) over 2min, red (`very-stale`) over 6min; market-closed
//     overrides BOTH amber and red; `marketOpen === null` (no client-side
//     model for the symbol's market, e.g. FUND/CRYPTO) gets no override
//   - the boundary/threshold math itself (amber/red cutoffs, market-closed
//     override, fresh-survives-close) is already exhaustively unit-tested
//     [frontend/src/utils/statusBar.test.ts] — these E2E tests exercise the
//     INTEGRATION wiring (real quote `ts` -> usePriceUpdates -> StatusBar ->
//     rendered label, with the real `getSetStatus`/`getUsStatus` clock logic),
//     not re-derive every boundary.
//
// `page.clock.setFixedTime()` pins `Date.now()`/`new Date()` in the page
// while leaving real timers running [node_modules/playwright-core/types/
// types.d.ts:20547-20564] — used here so `marketOpen` (computed from the real
// wall clock inside `getUsStatus()`) is deterministic instead of depending on
// whatever time the test happens to run.
//
// "● Live"/"○ Offline" from the WS connection is unchanged by bd:shotockviz-09j
// (StatusBar.tsx:56-63) — kept as its own smoke test, WS-only, no data_ready
// involved.
// ---------------------------------------------------------------------------
function statusLabel(page: import('@playwright/test').Page) {
  return page.locator('div.panel.border-t').getByText('ราคา NVDA', { exact: false });
}

test('F3: StatusBar shows Live when WS connects (unchanged by bd:shotockviz-09j)', async ({ page }) => {
  await mockStockAPIs(page);
  await mockAuthSession(page, MOCK_AUTH_ME);
  await mockWatchlistAPIs(page);
  await page.route('**/api/v1/stocks/quotes**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ NVDA: { price: 900, change: 1, change_pct: 0.1 } }),
    }),
  );
  // bd:shotockviz-pls (landed mid-session, commit 14cf42a — a THIRD
  // supersession Oliver's delegation did not flag): the WS handshake now
  // requires `?token=<jwt>` on the URL [frontend/src/utils/wsUrl.ts:15,
  // frontend/src/hooks/useWebSocket.ts:88-93]. The pattern must match the
  // query string too, or this falls through to the REAL (unmocked) socket,
  // which the backend now rejects (1008/403) for the fake mock token —
  // reproduced and confirmed: `**/api/ws/prices` (no trailing wildcard)
  // left the page on '○ Offline' 5/5 times before this fix.
  await page.routeWebSocket('**/api/ws/prices**', () => {});

  await page.goto('/');
  await page.waitForLoadState('networkidle');

  const statusBar = page.locator('div.panel.border-t');
  await expect(statusBar.getByText('● Live')).toBeVisible({ timeout: 5_000 });
});

test('F3: a fresh ts (<2min old) renders a recent Thai age label, not a fabricated wall clock', async ({ page }) => {
  // Time itself is irrelevant here — freshness bypasses the market-open
  // check entirely below the amber threshold [statusBar.ts:102-104] — fixed
  // anyway so the test is not flaky-by-construction.
  const nowMs = Date.UTC(2026, 8, 9, 20, 0, 0);
  await page.clock.setFixedTime(nowMs);
  await mockStockAPIs(page);
  await mockAuthSession(page, MOCK_AUTH_ME);
  await mockWatchlistAPIs(page);
  await page.route('**/api/v1/stocks/quotes**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ NVDA: { price: 900, change: 1, change_pct: 0.1, ts: Math.floor(nowMs / 1000) - 30 } }),
    }),
  );

  await page.goto('/');
  await page.waitForLoadState('networkidle');

  await expect(statusLabel(page)).toHaveText('ราคา NVDA: เมื่อครู่นี้');
});

test('F3: an old ts crosses amber (stale) then red (very-stale) while the market is open', async ({ page }) => {
  // Wed 2026-09-09 15:00 ET (epoch - 5h, marketStatus.ts:52-71) = mins 900,
  // inside the 570-960 regular-session window -> getUsStatus().open === true.
  const nowMs = Date.UTC(2026, 8, 9, 20, 0, 0);
  await page.clock.setFixedTime(nowMs);
  await mockStockAPIs(page);
  await mockAuthSession(page, MOCK_AUTH_ME);
  await mockWatchlistAPIs(page);

  let ageSec = 150; // 2m30s -> stale (amber): > AMBER_MS(120s), <= RED_MS(360s)
  await page.route('**/api/v1/stocks/quotes**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ NVDA: { price: 900, change: 1, change_pct: 0.1, ts: Math.floor(nowMs / 1000) - ageSec } }),
    }),
  );

  await page.goto('/');
  await page.waitForLoadState('networkidle');
  const label = statusLabel(page);
  await expect(label).toHaveText('ราคา NVDA: 2 นาทีที่แล้ว');

  ageSec = 400; // 6m40s -> very-stale (red): > RED_MS(360s)
  await page.reload();
  await page.waitForLoadState('networkidle');
  await expect(label).toHaveText('ราคา NVDA: 6 นาทีที่แล้ว');
});

test('F3: a closed market shows "ตลาดปิด" instead of a stale warning, but a fresh price after close still reads fresh', async ({ page }) => {
  // Sat 2026-09-12 — day===6 in getUsStatus() (marketStatus.ts:60-62) ->
  // closed all day regardless of time-of-day.
  const nowMs = Date.UTC(2026, 8, 12, 20, 0, 0);
  await page.clock.setFixedTime(nowMs);
  await mockStockAPIs(page);
  await mockAuthSession(page, MOCK_AUTH_ME);
  await mockWatchlistAPIs(page);

  let ageSec = 300; // would be stale (amber) if the market were open
  await page.route('**/api/v1/stocks/quotes**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ NVDA: { price: 900, change: 1, change_pct: 0.1, ts: Math.floor(nowMs / 1000) - ageSec } }),
    }),
  );

  await page.goto('/');
  await page.waitForLoadState('networkidle');
  const label = statusLabel(page);
  await expect(label).toHaveText('ราคา NVDA: ตลาดปิด');

  // statusBar.ts:87-89 — a genuinely fresh price still displays as fresh
  // even after the market has closed; the override only fires for
  // already-alarming staleness.
  ageSec = 30;
  await page.reload();
  await page.waitForLoadState('networkidle');
  await expect(label).toHaveText('ราคา NVDA: เมื่อครู่นี้');
});

test('F3: a missing ts shows "—" rather than a fabricated time', async ({ page }) => {
  await mockStockAPIs(page);
  await mockAuthSession(page, MOCK_AUTH_ME);
  await mockWatchlistAPIs(page);
  await page.route('**/api/v1/stocks/quotes**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({ NVDA: { price: 900, change: 1, change_pct: 0.1 } }), // no `ts` field
    }),
  );

  await page.goto('/');
  await page.waitForLoadState('networkidle');

  await expect(statusLabel(page)).toHaveText('ราคา NVDA: —');
});
