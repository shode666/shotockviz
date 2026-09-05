/**
 * Settings page + theme toggle tests
 * Covers: navbar gear link to /settings, theme switch, persistence, page sections.
 *
 * bd:ux-2026-09 g3 — SettingsModal replaced by a full `/settings` route
 * (03-design-notes.md §Settings). This file was rewritten to match.
 */
import { test, expect } from '@playwright/test';
import { mockStockAPIs, mockAuthSession, MOCK_AUTH_ME } from './helpers/mocks';

test.describe('Theme Toggle — navbar button', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
      localStorage.removeItem('theme');
    });
    await mockStockAPIs(page);
    await page.goto('/');
    // bd:ux-2026-09 item 6 fix — this describe was the only one without this
    // wait; under load the click below can race React hydration (button is
    // DOM-present after 'load' but its onClick isn't wired yet), making the
    // 'clicking theme toggle switches' test flaky (fails ~1/2 runs when the
    // suite runs alongside quinn-targeted.spec.ts, passes solo).
    await page.waitForLoadState('networkidle');
  });

  test('theme toggle button is visible in navbar', async ({ page }) => {
    await expect(page.locator('nav button[class*="rounded-lg"]').nth(0)).toBeVisible();
  });

  test('clicking theme toggle switches between dark and light', async ({ page }) => {
    // bd:ux-2026-09 item 6 fix — the innerHTML scan for 'Sun'/'Moon' never
    // matched (lucide-react renders <svg>, no such text node exists), so
    // the loop clicked nothing and the assertion below was comparing the
    // unchanged theme against itself. Navbar.tsx:157 has a stable
    // aria-label="สลับธีม" — use it directly.
    const initialTheme = await page.evaluate(() =>
      document.documentElement.getAttribute('data-theme'),
    );

    await page.getByRole('button', { name: 'สลับธีม' }).click();

    const newTheme = await page.evaluate(() =>
      document.documentElement.getAttribute('data-theme'),
    );

    if (initialTheme === 'dark') {
      expect(newTheme).toBe('light');
    } else {
      expect(newTheme).toBe('dark');
    }
  });

  test('theme persists after page reload', async ({ page }) => {
    // bd:ux-2026-09 item 6 fix — the describe's beforeEach registers an
    // addInitScript that removes localStorage 'theme' on every navigation,
    // including this test's own page.reload() below, wiping the value this
    // test sets *before* appStore's initTheme() ever runs on the reloaded
    // page (__root.tsx:94-97 reads localStorage on mount). Register a second
    // initScript that re-applies 'theme' after the cleanup one — initScripts
    // run in registration order, so this one wins on the reload.
    await page.addInitScript(() => localStorage.setItem('theme', 'light'));
    await page.evaluate(() => {
      localStorage.setItem('theme', 'light');
      document.documentElement.setAttribute('data-theme', 'light');
    });

    await page.reload();
    await page.waitForLoadState('networkidle');

    const theme = await page.evaluate(() =>
      document.documentElement.getAttribute('data-theme'),
    );
    expect(theme).toBe('light');
  });
});

test.describe('Settings Page — navigation', () => {
  test.beforeEach(async ({ page }) => {
    await mockStockAPIs(page);
    await mockAuthSession(page, MOCK_AUTH_ME);
    await page.goto('/');
  });

  test('gear icon in navbar links to /settings', async ({ page }) => {
    const gearLink = page.getByRole('link', { name: 'ตั้งค่า' });
    await expect(gearLink).toBeVisible();
    await gearLink.click();
    await expect(page).toHaveURL('/settings');
  });

  test('settings page has General / Chart / Notification side nav', async ({ page }) => {
    await page.goto('/settings');
    // bd:ux-2026-09 item 6 fix — unscoped 'Chart' collides with the top
    // Navbar's own "Chart" route link (strict-mode violation); scope to the
    // settings side-nav landmark (SettingsPage.tsx:46, aria-label="หมวดตั้งค่า").
    const sideNav = page.getByRole('navigation', { name: 'หมวดตั้งค่า' });
    await expect(sideNav.getByRole('link', { name: /General/ })).toBeVisible();
    await expect(sideNav.getByRole('link', { name: /Chart/ })).toBeVisible();
    await expect(sideNav.getByRole('link', { name: /Notification/ })).toBeVisible();
  });

  test('settings page has Dark and Light theme cards', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.getByText('Dark', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('Light', { exact: true }).first()).toBeVisible();
  });

  test('settings page has Timezone selector', async ({ page }) => {
    await page.goto('/settings');
    // bd:ux-2026-09 item 6 fix — unscoped 'Timezone' matches 3 nodes (the
    // section title div, the sr-only <label>, and the helper paragraph
    // substring) — same .first() pattern already used below for Dark/Light.
    await expect(page.getByText('Timezone', { exact: true }).first()).toBeVisible();
    await expect(page.locator('#settings-tz')).toBeVisible();
  });

  test('settings page has Chart Defaults section', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.getByText('Chart Defaults')).toBeVisible();
  });

  test('settings page has a Telegram Chat ID field (local state only)', async ({ page }) => {
    await page.goto('/settings');
    const input = page.locator('#settings-telegram');
    await expect(input).toBeVisible();
    await input.fill('128845067');
    await expect(input).toHaveValue('128845067');
  });

  test('clicking "Light" card switches to light mode', async ({ page }) => {
    await page.addInitScript(() => localStorage.setItem('theme', 'dark'));
    await page.goto('/settings');
    // bd:ux-2026-09 user-reported regression investigation — same hydration
    // race as the item-6 fix in the describe above (line 20-25): this is a
    // SECOND page.goto() (the describe's own beforeEach already navigated to
    // '/'), so it re-triggers a full document load + re-hydration. goto()
    // only waits for the browser 'load' event, not for React to finish
    // hydrating and wire up this button's onClick — the click below landed
    // on a DOM-present-but-not-yet-interactive button and did nothing.
    // Verified via repro: data-theme stayed `null` after both the goto AND
    // the click without this wait [output: scratchpad/diag-settings-repro.mjs
    // vs diag-settings-repro2.mjs — same page, same clicks, only difference
    // is this wait — repro2 resolves 'dark' then 'light' correctly].
    await page.waitForLoadState('networkidle');

    await page.getByRole('button', { name: 'Light', exact: false }).first().click();

    const theme = await page.evaluate(() =>
      document.documentElement.getAttribute('data-theme'),
    );
    expect(theme).toBe('light');
  });
});

test.describe('Settings Page — Telegram save flow (bd:features-2026-09 slice 3, Quinn Phase 3b)', () => {
  // Covers the actual PATCH /api/v1/auth/settings round-trip — the pre-existing
  // 'has a Telegram Chat ID field (local state only)' test above only checks the
  // <input> DOM value and never hits the network. These specs hit GET on load and
  // PATCH on save, matching authService.ts / SettingsPage.tsx:51-66's real wiring.
  const SETTINGS_URL = '**/api/v1/auth/settings';

  test.beforeEach(async ({ page }) => {
    await mockStockAPIs(page);
    await mockAuthSession(page, MOCK_AUTH_ME);
  });

  test('save with a valid-looking chat id shows the success toast (test message sent)', async ({ page }) => {
    let patchBody: unknown = null;
    await page.route(SETTINGS_URL, (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ data: { telegram_chat_id: null }, meta: {} }),
        });
      }
      if (route.request().method() === 'PATCH') {
        patchBody = route.request().postDataJSON();
        // Real backend behavior on success (auth.py:189-215): persists and
        // echoes back the saved row, enveloped like every other /api/v1/* route.
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ data: { telegram_chat_id: '128845067' }, meta: {} }),
        });
      }
      return route.continue();
    });

    await page.goto('/settings');
    const input = page.locator('#settings-telegram');
    await expect(input).toBeVisible();
    await input.fill('128845067');
    await page.getByRole('button', { name: 'บันทึก' }).click();

    // SettingsPage.tsx:55-59 — non-empty chat id -> the "test message sent" copy
    await expect(page.getByText('ส่งข้อความทดสอบไปที่ Telegram สำเร็จ')).toBeVisible();
    expect(patchBody).toEqual({ telegram_chat_id: '128845067' });

    // Save button must return to its resting label — no stuck "กำลังบันทึก..." spinner state
    await expect(page.getByRole('button', { name: 'บันทึก' })).toBeVisible();
  });

  test('save with a chat id the bot never talked to shows a clear error — NOT a silent save', async ({ page }) => {
    let patchCallCount = 0;
    const BACKEND_ERROR_MSG =
      'ส่งข้อความทดสอบไป Telegram ไม่สำเร็จ — ตรวจสอบว่าคุยกับ @ShotockVizBot แล้วพิมพ์ /start ก่อน (Forbidden: bot was blocked by the user)';

    await page.route(SETTINGS_URL, (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ data: { telegram_chat_id: null }, meta: {} }),
        });
      }
      if (route.request().method() === 'PATCH') {
        patchCallCount += 1;
        // Real backend behavior on failure (auth.py:206-212) — 422, enveloped
        // error shape per schemas/envelope.py's install_error_envelope, message
        // surfaced verbatim by api.ts:92 (body.meta.error.message) as a toast.
        // NOT in SILENT_PATHS (api.ts:38 has no '/auth/settings' entry) so this
        // must actually reach the user, unlike /quote or /sr-levels failures.
        return route.fulfill({
          status: 422,
          contentType: 'application/json',
          body: JSON.stringify({ data: null, meta: { error: { message: BACKEND_ERROR_MSG } } }),
        });
      }
      return route.continue();
    });

    await page.goto('/settings');
    const input = page.locator('#settings-telegram');
    await input.fill('999999999');
    await page.getByRole('button', { name: 'บันทึก' }).click();

    // The real backend error message must surface, not a generic failure or —
    // worse — nothing at all (a silent save would show no toast whatsoever).
    await expect(page.getByText(/ส่งข้อความทดสอบไป Telegram ไม่สำเร็จ/)).toBeVisible();

    // Must NOT show the success copy from the sibling test above.
    await expect(page.getByText('บันทึกแล้ว — ส่งข้อความทดสอบไปที่ Telegram สำเร็จ')).not.toBeVisible();

    expect(patchCallCount).toBe(1);

    // Reload with GET still reporting the OLD (unset) value — proves the failed
    // PATCH did not silently persist server-side despite the error toast (this
    // is the "not a silent save" half of the AC — SettingsPage.tsx has no local
    // optimistic-write path, so this also guards against a future regression
    // that adds one without re-checking persistence).
    await page.reload();
    await page.waitForLoadState('networkidle');
    await expect(input).toHaveValue('');
  });

  test('save button is disabled and shows the saving label while the request is in flight', async ({ page }) => {
    await page.route(SETTINGS_URL, async (route) => {
      if (route.request().method() === 'GET') {
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ data: { telegram_chat_id: null }, meta: {} }),
        });
      }
      if (route.request().method() === 'PATCH') {
        // Deliberate delay so the in-flight 'กำลังบันทึก...' state (isSaving=true,
        // SettingsPage.tsx:38,52,193) is observable instead of racing past it.
        await new Promise((r) => setTimeout(r, 300));
        return route.fulfill({
          status: 200,
          contentType: 'application/json',
          body: JSON.stringify({ data: { telegram_chat_id: '128845067' }, meta: {} }),
        });
      }
      return route.continue();
    });

    await page.goto('/settings');
    await page.locator('#settings-telegram').fill('128845067');
    const saveBtn = page.getByRole('button', { name: 'บันทึก' });
    await saveBtn.click();

    await expect(page.getByRole('button', { name: 'กำลังบันทึก...' })).toBeDisabled();
    await expect(page.getByRole('button', { name: 'บันทึก' })).toBeVisible();
  });
});

test.describe('Navbar User Dropdown', () => {
  test.beforeEach(async ({ page }) => {
    await mockStockAPIs(page);
    await mockAuthSession(page, MOCK_AUTH_ME);
    await page.goto('/');
  });

  test('clicking avatar opens dropdown with user info', async ({ page }) => {
    const avatarBtn = page.getByRole('button', { name: 'T', exact: true });
    await avatarBtn.click();
    await expect(page.getByText('Test User')).toBeVisible();
    await expect(page.getByText('test@example.com')).toBeVisible();
  });

  test('dropdown has Logout button', async ({ page }) => {
    const avatarBtn = page.getByRole('button', { name: 'T', exact: true });
    await avatarBtn.click();
    await expect(page.getByRole('button', { name: /Logout/ })).toBeVisible();
  });

  test('clicking outside dropdown closes it', async ({ page }) => {
    const avatarBtn = page.getByRole('button', { name: 'T', exact: true });
    await avatarBtn.click();
    await expect(page.getByText('Test User')).toBeVisible();

    await page.mouse.click(200, 400);
    await expect(page.getByText('Test User')).not.toBeVisible();
  });

  test('dropdown uses glassmorphism (glass-dropdown class)', async ({ page }) => {
    const avatarBtn = page.getByRole('button', { name: 'T', exact: true });
    await avatarBtn.click();

    const dropdown = page.locator('.glass-dropdown');
    await expect(dropdown).toBeVisible();
  });
});
