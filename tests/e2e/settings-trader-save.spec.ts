/**
 * bd:shotockviz-649.1.1 — "no component-level test covers the settings
 * save-failure path".
 *
 * bd:shotockviz-649.1 added GET/PATCH /api/v1/settings/trader
 * (backend/api/routes/settings.py) as the server-side home for two
 * previously client-only-or-nonexistent thresholds:
 *   - ConcentrationLimitPanel.tsx  (frontend/src/components/portfolio/)
 *   - SettingsPage.tsx's gap-threshold field (frontend/src/components/pages/)
 *
 * Neither component has ever had a component-level test — this repo's
 * frontend harness only covers pure modules under src/utils/* (confirmed:
 * no ConcentrationLimitPanel.test.tsx / SettingsPage.test.tsx precedent
 * exists). This file is that coverage, entirely through Playwright against
 * routed (never real) requests to /api/v1/settings/trader.
 *
 * bd:shotockviz-tjh (663e03f) changed 401 handling: PATCH /settings/trader
 * is deliberately NOT flagged `skipAuthClearOn401`, so a 401 on save is a
 * full logout by design, not an inline save error. That is covered as its
 * own scenario ("401-on-save clears the session") — the "shows inline
 * error, does not persist" scenarios below use 500 (a real backend/network
 * failure), never 401, so as not to lock in the wrong failure mode.
 *
 * No real backend row is ever touched: every /api/v1/settings/trader,
 * /api/v1/auth/settings, and /api/v1/portfolio* request in this file is
 * intercepted with page.route(...).fulfill(...) — none call route.continue()
 * for these paths, so nothing reaches the dev-stack Postgres row for user id 1.
 */
import { test, expect } from '@playwright/test';
import { mockStockAPIs, mockAuthSession, MOCK_AUTH_ME } from './helpers/mocks';

const TRADER_URL = '**/api/v1/settings/trader';

// ---------------------------------------------------------------------------
// Shared portfolio fixtures — just enough for ConcentrationLimitPanel to
// render (hasAllocation() needs a non-empty `allocation.slices` or
// `allocation.excluded`, utils/allocation.ts:213-215) without dragging in
// the whole portfolio.spec.ts fixture set.
// ---------------------------------------------------------------------------
const MOCK_HOLDING_SINGLE = [
  {
    symbol: 'PTT.BK',
    qty: 1000,
    avg_cost: 32.5,
    current_price: 35.5,
    current_value: 35500,
    unrealized_pl: 3000,
    unrealized_pl_pct: 9.23,
    currency: 'THB',
  },
];

/**
 * Mocks GET /api/v1/portfolio/analytics (main page fetch, no query param)
 * AND the panel's own GET /api/v1/portfolio/analytics?concentration_limit_pct=
 * with the SAME handler (usePortfolioData.ts + ConcentrationLimitPanel.tsx
 * both hit the same path — the query param is the only difference), plus
 * GET /api/v1/portfolio (transactions) so usePortfolioData's Promise.all
 * resolves. Pattern mirrors portfolio.spec.ts's mockPortfolioAPI.
 */
async function mockPortfolioWithAllocation(page: any) {
  await page.route('**/api/v1/portfolio**', (route: any) => {
    const url = route.request().url();
    if (url.includes('/analytics')) {
      const limitParam = new URL(url).searchParams.get('concentration_limit_pct');
      const limit = limitParam ? Number(limitParam) : 25;
      return route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({
          base_currency: 'THB',
          total_value: 35500,
          total_cost: 32500,
          unrealized_pl: 3000,
          unrealized_pl_pct: 9.23,
          holdings: MOCK_HOLDING_SINGLE,
          has_pending_prices: false,
          allocation: { slices: [{ symbol: 'PTT.BK', value_base: 35500, weight_pct: 100 }], excluded: [] },
          concentration: { limit_pct: limit, breaches: [], not_checked: [] },
        }),
      });
    }
    if (url.includes('/performance')) {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
    }
    return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([]) });
  });
}

const concentrationCacheKey = (uid: number | string) => `shotockviz.concentration_limit_pct.${uid}`;

// ===========================================================================
// Surface 1: SettingsPage.tsx — gap threshold (gap_min_pct)
// ===========================================================================
test.describe('649.1.1 — SettingsPage gap threshold save (settings/trader)', () => {
  test.beforeEach(async ({ page }) => {
    await mockStockAPIs(page);
    await mockAuthSession(page, MOCK_AUTH_ME);
    // SettingsPage.handleSave fires this PATCH concurrently (Promise.allSettled)
    // alongside the gap_min_pct PATCH under test — must never reach the real
    // backend or it would send a live Telegram test message / touch real rows.
    await page.route('**/api/v1/auth/settings', (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ data: { telegram_chat_id: null }, meta: {} }),
        });
      }
      if (route.request().method() === 'PATCH') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ data: { telegram_chat_id: null }, meta: {} }),
        });
      }
      return route.continue();
    });
  });

  test('successful save persists across reload', async ({ page }) => {
    let savedGapMinPct: number | null = null;
    await page.unroute(TRADER_URL); // remove mockStockAPIs' default 200-null-both handler
    await page.route(TRADER_URL, (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ concentration_limit_pct: null, gap_min_pct: savedGapMinPct }),
        });
      }
      if (route.request().method() === 'PATCH') {
        const body = route.request().postDataJSON();
        savedGapMinPct = body.gap_min_pct;
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ concentration_limit_pct: null, gap_min_pct: savedGapMinPct }),
        });
      }
      return route.continue();
    });

    await page.goto('/settings');
    const input = page.locator('#settings-gap-min-pct');
    await expect(input).toHaveValue(''); // hydrated null -> unset, per SettingsPage.tsx:131

    await input.fill('3.5');
    await page.getByRole('button', { name: 'บันทึก' }).click();

    // Save completed, no inline error, button back to resting label.
    await expect(page.getByRole('button', { name: 'บันทึก' })).toBeVisible();
    await expect(page.locator('[role="alert"]', { hasText: 'บันทึกเกณฑ์ Gap ไม่สำเร็จ' })).toHaveCount(0);

    await page.reload();
    await page.waitForLoadState('networkidle');
    // The ONLY source for this field on a fresh mount is the GET hydrate
    // (SettingsPage.tsx has no localStorage cache for gap_min_pct, unlike
    // ConcentrationLimitPanel) — so a value surviving reload here proves the
    // PATCH actually reached and was echoed back by (mocked) settings/trader,
    // not a client-side artifact.
    await expect(page.locator('#settings-gap-min-pct')).toHaveValue('3.5');
  });

  test('failed save (500) shows the inline error and does NOT persist', async ({ page }) => {
    let patchCallCount = 0;
    await page.unroute(TRADER_URL);
    await page.route(TRADER_URL, (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ concentration_limit_pct: null, gap_min_pct: null }),
        });
      }
      if (route.request().method() === 'PATCH') {
        patchCallCount += 1;
        return route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Internal Server Error' }),
        });
      }
      return route.continue();
    });

    await page.goto('/settings');
    await page.locator('#settings-gap-min-pct').fill('4');
    await page.getByRole('button', { name: 'บันทึก' }).click();

    // SettingsPage.tsx:171-177 — the field-local inline error, NOT the global
    // toast (which would say something else). Exact string, not a substring
    // match on shared boilerplate, per this repo's own quality-bar history
    // (getByText('PTT') / /bg-violet-500/ false-positive incidents).
    await expect(page.getByText('บันทึกเกณฑ์ Gap ไม่สำเร็จ ลองใหม่อีกครั้ง')).toBeVisible();
    expect(patchCallCount).toBe(1);

    // Must NOT be a 401/logout path — session stays intact on a plain 500.
    await expect(page.getByRole('button', { name: 'T', exact: true })).toBeVisible();

    // Reload with GET still reporting the pre-save (unset) value — proves the
    // failed PATCH never silently persisted despite the inline error copy.
    await page.reload();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('#settings-gap-min-pct')).toHaveValue('');
  });
});

// ===========================================================================
// Surface 2: ConcentrationLimitPanel.tsx — concentration_limit_pct
// ===========================================================================
test.describe('649.1.1 — ConcentrationLimitPanel save (settings/trader)', () => {
  test.beforeEach(async ({ page }) => {
    await mockStockAPIs(page);
    await mockAuthSession(page, MOCK_AUTH_ME);
    await mockPortfolioWithAllocation(page);
  });

  test('successful save persists across reload', async ({ page }) => {
    let savedLimit: number | null = null;
    await page.unroute(TRADER_URL);
    await page.route(TRADER_URL, (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ concentration_limit_pct: savedLimit, gap_min_pct: null }),
        });
      }
      if (route.request().method() === 'PATCH') {
        const body = route.request().postDataJSON();
        savedLimit = body.concentration_limit_pct;
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ concentration_limit_pct: savedLimit, gap_min_pct: null }),
        });
      }
      return route.continue();
    });

    await page.goto('/portfolio');
    const panel = page.locator('[data-testid="concentration-limit"]');
    await expect(panel).toBeVisible();
    const input = panel.locator('#concentration-limit-input');
    await expect(input).toHaveValue('25'); // DEFAULT_CONCENTRATION_LIMIT_PCT, nothing saved server-side yet

    await input.fill('40');
    await panel.getByRole('button', { name: 'บันทึก' }).click();
    await expect(panel.getByRole('button', { name: 'บันทึก' })).toBeVisible();
    await expect(page.locator('#concentration-limit-error')).toHaveCount(0);

    // ConcentrationLimitPanel ALSO writes a same-device localStorage cache on
    // a successful save (concentrationLimit.ts::saveConcentrationLimitPct) —
    // clearing it before reload forces the post-reload value to come from
    // nowhere but the GET /settings/trader hydrate, so this actually proves
    // the SERVER round trip, not the client cache reproducing itself.
    await page.evaluate((key) => localStorage.removeItem(key), concentrationCacheKey(MOCK_AUTH_ME.id));

    await page.reload();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('#concentration-limit-input')).toHaveValue('40');
  });

  test('failed save (500) shows the inline error and does NOT persist', async ({ page }) => {
    let patchCallCount = 0;
    await page.unroute(TRADER_URL);
    await page.route(TRADER_URL, (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ concentration_limit_pct: null, gap_min_pct: null }),
        });
      }
      if (route.request().method() === 'PATCH') {
        patchCallCount += 1;
        return route.fulfill({
          status: 500,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Internal Server Error' }),
        });
      }
      return route.continue();
    });

    await page.goto('/portfolio');
    const panel = page.locator('[data-testid="concentration-limit"]');
    const input = panel.locator('#concentration-limit-input');
    await expect(input).toHaveValue('25');

    await input.fill('60');
    await panel.getByRole('button', { name: 'บันทึก' }).click();

    // ConcentrationLimitPanel.tsx:162 — exact inline copy, scoped to the
    // panel's own #concentration-limit-error node (role="alert").
    await expect(page.locator('#concentration-limit-error')).toHaveText(
      'บันทึกไม่สำเร็จ — ค่าที่แสดงอยู่อาจไม่ตรงกับที่บันทึกไว้ ลองใหม่อีกครั้ง',
    );
    expect(patchCallCount).toBe(1);

    // Not a 401/logout path.
    await expect(page.getByRole('button', { name: 'T', exact: true })).toBeVisible();

    // The rejected value must not have reached the localStorage cache either
    // (ConcentrationLimitPanel.tsx only calls saveConcentrationLimitPct AFTER
    // a successful PATCH) — a stale "60" here would let a future reload show
    // the rejected value as if it had been saved.
    const cached = await page.evaluate(
      (key) => localStorage.getItem(key),
      concentrationCacheKey(MOCK_AUTH_ME.id),
    );
    expect(cached).not.toBe('60');

    await page.reload();
    await page.waitForLoadState('networkidle');
    await expect(page.locator('#concentration-limit-input')).toHaveValue('25');
  });
});

// ===========================================================================
// 401-on-save: deliberately a logout, not an inline error (bd:shotockviz-tjh)
// ===========================================================================
test.describe('649.1.1 — 401 on PATCH /settings/trader is a logout, not a save error', () => {
  test.beforeEach(async ({ page }) => {
    await mockStockAPIs(page);
    await mockAuthSession(page, MOCK_AUTH_ME);
    await mockPortfolioWithAllocation(page);
  });

  test('a 401 on save clears the session (ConcentrationLimitPanel)', async ({ page }) => {
    await page.unroute(TRADER_URL);
    await page.route(TRADER_URL, (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ concentration_limit_pct: null, gap_min_pct: null }),
        });
      }
      if (route.request().method() === 'PATCH') {
        return route.fulfill({
          status: 401,
          contentType: 'application/json',
          body: JSON.stringify({ detail: 'Not authenticated' }),
        });
      }
      return route.continue();
    });

    await page.goto('/portfolio');
    const avatarBtn = page.getByRole('button', { name: 'T', exact: true });
    await expect(avatarBtn).toBeVisible(); // authenticated before the save

    const panel = page.locator('[data-testid="concentration-limit"]');
    await panel.locator('#concentration-limit-input').fill('50');
    await panel.getByRole('button', { name: 'บันทึก' }).click();

    // PATCH /settings/trader is NOT flagged skipAuthClearOn401
    // (apiErrorHandler.ts:130-136) — a 401 here clears the session via
    // authStore.handleUnauthorizedResponse(), which removes access_token and
    // flips isAuthenticated false. The avatar button only renders when
    // isAuthenticated (settings.spec.ts's own Navbar User Dropdown tests key
    // off the exact same button), so its disappearance is the load-bearing
    // proof of logout, not merely "some error occurred".
    await expect(avatarBtn).not.toBeVisible();
    const token = await page.evaluate(() => localStorage.getItem('access_token'));
    expect(token).toBeNull();

    // bd:shotockviz-2qw — no inline save error either. NOTE, honestly: this
    // assertion CANNOT fail on this surface and is not the proof of the fix.
    // PortfolioPage.tsx:352 gates its whole body on `isAuthenticated`, so the
    // logout unmounts the panel and takes any error node with it — verified
    // by deleting the component's guard and watching this test still pass.
    // It is kept as a regression guard for the day that page stops gating.
    // The load-bearing proof lives in the SettingsPage test below, which has
    // no auth gate at all and therefore really does render both signals.
    await expect(page.locator('#concentration-limit-error')).toHaveCount(0);
  });
});

// ---------------------------------------------------------------------------
// bd:shotockviz-2qw — the surface where the double signal is really visible.
//
// SettingsPage has NO `isAuthenticated` gate (grep: 0 hits), so it keeps
// rendering after the session is cleared. Before the fix, a 401 mid-save
// logged the trader out AND left "บันทึกเกณฑ์ Gap ไม่สำเร็จ ลองใหม่อีกครั้ง"
// on screen, pointing them back at a form they no longer had a session for.
// Both signals were individually correct; showing them together was not.
// ---------------------------------------------------------------------------
test.describe('2qw — a 401 mid-save is a logout only, not also a save error', () => {
  test.beforeEach(async ({ page }) => {
    await mockStockAPIs(page);
    await mockAuthSession(page, MOCK_AUTH_ME);
    // Same reason as the 649.1.1 SettingsPage block above: handleSave fires a
    // concurrent PATCH /auth/settings, and the page GETs it on mount. Left
    // unmocked, that GET 401s against the real backend and logs the session
    // out before the test has even started — which is what happened on the
    // first run of this test (the avatar was already gone at line 1).
    await page.route('**/api/v1/auth/settings', (route) =>
      route.fulfill({
        status: 200,
        contentType: 'application/json',
        body: JSON.stringify({ data: { telegram_chat_id: null }, meta: {} }),
      }),
    );
  });

  test('SettingsPage: 401 on save clears the session and shows NO inline gap error', async ({ page }) => {
    await page.unroute(TRADER_URL);
    await page.route(TRADER_URL, (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ concentration_limit_pct: null, gap_min_pct: null }),
        });
      }
      return route.fulfill({
        status: 401,
        contentType: 'application/json',
        body: JSON.stringify({ detail: 'Not authenticated' }),
      });
    });

    await page.goto('/settings');
    const avatarBtn = page.getByRole('button', { name: 'T', exact: true });
    await expect(avatarBtn).toBeVisible(); // authenticated before the save

    await page.locator('#settings-gap-min-pct').fill('3.5');
    await page.getByRole('button', { name: 'บันทึก' }).click();

    // the logout half still happens — bd:shotockviz-tjh's decision stands
    await expect(avatarBtn).not.toBeVisible();
    expect(await page.evaluate(() => localStorage.getItem('access_token'))).toBeNull();

    // ...and the save-error half does not. This page is still mounted, so the
    // element WOULD be here if the component still set it — which is what
    // makes this assertion load-bearing where the Portfolio one is not.
    await expect(page.getByText('บันทึกเกณฑ์ Gap ไม่สำเร็จ ลองใหม่อีกครั้ง')).toHaveCount(0);
    await expect(page.locator('#settings-gap-min-pct')).toBeVisible(); // page really is still rendered
  });
});
