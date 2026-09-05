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
// F11 — Alert EXPIRED status renders a distinct label/color from `inactive`
// (paused). Guards the exact bug this feature fixes: EXPIRED silently
// falling through to "หยุดชั่วคราว".
// ---------------------------------------------------------------------------
test('F11: alert with status EXPIRED shows "หมดอายุ", distinct from inactive "หยุดชั่วคราว"', async ({ page }) => {
  await mockStockAPIs(page);
  await mockAuthSession(page, MOCK_AUTH_ME);
  await mockWatchlistAPIs(page);
  await page.route('**/api/v1/alerts**', (route) =>
    route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify([
        { id: 1, symbol: 'PTT.BK', alert_type: 'Price Above', condition: 'above', value: 40, channel: 'in_app', status: 'EXPIRED', is_active: false },
        { id: 2, symbol: 'AAPL', alert_type: 'Price Below', condition: 'below', value: 170, channel: 'in_app', status: null, is_active: false },
      ]),
    }),
  );

  await page.goto('/alerts');
  await page.waitForLoadState('networkidle');

  await expect(page.getByText('หมดอายุ')).toBeVisible({ timeout: 8_000 });
  await expect(page.getByText('หยุดชั่วคราว')).toBeVisible();
  // Distinct elements, not the same text rendered twice.
  expect(await page.getByText('หมดอายุ').count()).toBeGreaterThan(0);
  expect(await page.getByText('หยุดชั่วคราว').count()).toBeGreaterThan(0);
});

// ---------------------------------------------------------------------------
// F3 — StatusBar reflects real WS connection state and only updates its
// timestamp on a real, *qualifying* `data_ready` message (not a wall-clock
// tick, and — per r2, `03b-bella-spec-r2-F3.md` — not any `data_ready`
// regardless of data_type/symbol either).
//
// r2 scope (Bella): a message qualifies only when
// `data_type === 'quote'` AND (`symbol === selectedStock.sym` OR
// `symbol === '*'`). `history`/`fundamentals` for the SAME symbol, and
// `quote` for a DIFFERENT symbol, must NOT move the timestamp — this is the
// exact Chris Medium #1 regression (`30-chris-review.md`) this revision
// exists to close, so both negative cases get their own assertions here,
// not just the positive path. Label copy is now `ราคา {sym} อัปเดตล่าสุด:
// …` (AC7) — asserted literally, not just via the old generic substring.
//
// Known cross-cutting fact (Oliver, 20-verify.md): caddy/Caddyfile.dev's
// `/api/ws/*` Connection/Upgrade header_up lines broke WS entirely on Caddy
// v2.11.4 (backend 404 instead of 101) — Oliver already removed those 2
// lines from Caddyfile.dev. This test uses page.routeWebSocket, which
// intercepts at the browser layer before any request reaches Caddy, so it
// exercises the *frontend* contract (StatusBar + useWebSocket) independently
// of that infra bug — it would NOT have caught the Caddy bug itself. See
// 31-quinn-review.md §4 for the infra-level check.
// ---------------------------------------------------------------------------
// Reads the whole "ราคา {sym} อัปเดตล่าสุด: ..." span via a substring match
// that is ALWAYS present (dash or real time) — deliberately not a locator
// matching only the timestamp regex. A locator that only matches when a
// timestamp is present will hang for the full test timeout (30s, not 5s)
// if the value the test is waiting on never appears, instead of failing
// fast — that cost real debugging time writing the AC3/AC4 regression
// checks below and is recorded here so the next author doesn't repeat it.
function statusLabel(page: import('@playwright/test').Page) {
  return page.locator('div.panel.border-t').getByText('อัปเดตล่าสุด:', { exact: false });
}

test('F3: StatusBar shows Live when WS connects, Offline when it does not, and the timestamp only moves on a same-symbol quote data_ready', async ({ page }) => {
  await mockStockAPIs(page);
  await mockAuthSession(page, MOCK_AUTH_ME);
  await mockWatchlistAPIs(page);

  let sendMessage: ((msg: string) => void) | null = null;
  await page.routeWebSocket('**/api/ws/prices', (ws) => {
    sendMessage = (msg: string) => ws.send(msg);
  });

  await page.goto('/');
  await page.waitForLoadState('networkidle');

  const statusBar = page.locator('div.panel.border-t');
  const label = statusLabel(page);
  await expect(statusBar.getByText('● Live')).toBeVisible({ timeout: 5_000 });
  await expect(statusBar.getByText('Delayed 15', { exact: false })).toHaveCount(0);
  // AC7 (label wording): must say "ราคา {sym}", not the bare generic label.
  // appStore's default selectedStock.sym is 'NVDA' (appStore.ts).
  await expect(label).toHaveText('ราคา NVDA อัปเดตล่าสุด: —');

  expect(sendMessage, 'WS route handler must have fired').not.toBeNull();

  // AC3 r2 / AC4 (trivial ordering — no real value has ever arrived yet, so
  // "unchanged" and "still dash" happen to be the same observation). This
  // is NOT the meaningful regression guard — see the two dedicated tests
  // below for the case Chris actually found (wrong-type/-symbol message
  // arriving AFTER a real one).
  sendMessage!(JSON.stringify({ type: 'data_ready', data_type: 'history', symbol: 'NVDA', timeframe: '1D' }));
  await expect(label).toHaveText('ราคา NVDA อัปเดตล่าสุด: —');
  sendMessage!(JSON.stringify({ type: 'data_ready', data_type: 'quote', symbol: 'AAPL' }));
  await expect(label).toHaveText('ราคา NVDA อัปเดตล่าสุด: —');

  // AC1 (qualify — same symbol): the one message that IS allowed through.
  sendMessage!(JSON.stringify({ type: 'data_ready', data_type: 'quote', symbol: 'NVDA' }));
  await expect(label).not.toHaveText('ราคา NVDA อัปเดตล่าสุด: —');
  const firstStamp = (await label.textContent())!;

  // Wait 2s of real wall-clock time with no second data_ready — the old
  // implementation ticked every 1s via setInterval; the fixed one must not.
  await page.waitForTimeout(2_000);
  await expect(label).toHaveText(firstStamp);
});

// ---------------------------------------------------------------------------
// F3 r2 — AC3/AC4 regression guard, isolated. This is the ask from Oliver's
// delegation verbatim: "Dave believes your existing StatusBar assertions
// still pass because they substring-match. Verify that yourself rather than
// trusting it ... that is the exact regression Chris found, and right now
// nothing guards it end-to-end." The trivial form of AC3/AC4 (wrong
// type/symbol arriving while the label is ALREADY "—") passes regardless of
// whether the filter works, because "unchanged" and "still dash" are the
// same observable. The only form that actually exercises the filter is: a
// REAL qualifying timestamp is on screen, then a wrong-type/-symbol message
// arrives — does the label keep the real value ("unchanged from its prior
// value", `03b-bella-spec-r2-F3.md` AC3) or does it revert to "—"?
//
// RESULT: it reverts. `useWebSocket.ts:71` calls `setPayloadRef.current(data)`
// unconditionally for every `data_ready`, unconditionally overwriting the
// single global `appStore.dataReadyPayload` object regardless of whether it
// qualifies. `getLastQuoteTimestamp` (`utils/statusBar.ts`) is a pure,
// stateless filter over only the CURRENT `dataReadyPayload` — it has no
// memory of the last-qualifying value, so once a non-qualifying message
// overwrites the store, StatusBar's derived timestamp reverts to "—" even
// though a real, still-fresh quote update happened moments earlier. This is
// a genuine, unaddressed product bug against Bella's own r2 spec/verify
// steps (§Verify steps 2→3), not test-drift — reported to Oliver, NOT fixed
// here (this delegation's constraint is tests/ only, no frontend/src edits).
// ---------------------------------------------------------------------------
test('F3 r2 AC3 REGRESSION (real bug, not fixed here): a same-symbol history data_ready arriving AFTER a real quote update must leave the timestamp unchanged — it currently resets to "—"', async ({ page }) => {
  await mockStockAPIs(page);
  await mockAuthSession(page, MOCK_AUTH_ME);
  await mockWatchlistAPIs(page);

  let sendMessage: ((msg: string) => void) | null = null;
  await page.routeWebSocket('**/api/ws/prices', (ws) => {
    sendMessage = (msg: string) => ws.send(msg);
  });

  await page.goto('/');
  await page.waitForLoadState('networkidle');
  const label = statusLabel(page);

  sendMessage!(JSON.stringify({ type: 'data_ready', data_type: 'quote', symbol: 'NVDA' }));
  await expect(label).not.toHaveText('ราคา NVDA อัปเดตล่าสุด: —');
  const firstStamp = (await label.textContent())!;

  sendMessage!(JSON.stringify({ type: 'data_ready', data_type: 'history', symbol: 'NVDA', timeframe: '1D' }));
  // Bounded (3s, not the 30s test-timeout default) so this fails fast and
  // legibly instead of hanging — see the `statusLabel` comment above.
  await expect(
    label,
    'AC3 r2 (03b-bella-spec-r2-F3.md): timestamp must stay at its prior value, not reset to "—". ' +
      'Root cause: useWebSocket.ts unconditionally overwrites appStore.dataReadyPayload for every ' +
      'data_ready, and getLastQuoteTimestamp has no memory of the last qualifying value.',
  ).toHaveText(firstStamp, { timeout: 3_000 });
});

test('F3 r2 AC4 REGRESSION (real bug, not fixed here): an other-symbol quote data_ready arriving AFTER a real quote update must leave the timestamp unchanged — it currently resets to "—"', async ({ page }) => {
  await mockStockAPIs(page);
  await mockAuthSession(page, MOCK_AUTH_ME);
  await mockWatchlistAPIs(page);

  let sendMessage: ((msg: string) => void) | null = null;
  await page.routeWebSocket('**/api/ws/prices', (ws) => {
    sendMessage = (msg: string) => ws.send(msg);
  });

  await page.goto('/');
  await page.waitForLoadState('networkidle');
  const label = statusLabel(page);

  sendMessage!(JSON.stringify({ type: 'data_ready', data_type: 'quote', symbol: 'NVDA' }));
  await expect(label).not.toHaveText('ราคา NVDA อัปเดตล่าสุด: —');
  const firstStamp = (await label.textContent())!;

  sendMessage!(JSON.stringify({ type: 'data_ready', data_type: 'quote', symbol: 'AAPL' }));
  await expect(
    label,
    'AC4 (03b-bella-spec-r2-F3.md): a different symbol\'s quote must not move NVDA\'s timestamp. ' +
      'Same root cause as the AC3 regression test above (dataReadyPayload is a single overwritten slot).',
  ).toHaveText(firstStamp, { timeout: 3_000 });
});
