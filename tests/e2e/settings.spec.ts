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
  });

  test('theme toggle button is visible in navbar', async ({ page }) => {
    await expect(page.locator('nav button[class*="rounded-lg"]').nth(0)).toBeVisible();
  });

  test('clicking theme toggle switches between dark and light', async ({ page }) => {
    const initialTheme = await page.evaluate(() =>
      document.documentElement.getAttribute('data-theme'),
    );

    const navBtns = page.locator('nav button');
    for (let i = 0; i < await navBtns.count(); i++) {
      const btn = navBtns.nth(i);
      const html = await btn.innerHTML();
      if (html.includes('Sun') || html.includes('Moon') || html.includes('sun') || html.includes('moon')) {
        await btn.click();
        break;
      }
    }

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
    await expect(page.getByRole('link', { name: /General/ })).toBeVisible();
    await expect(page.getByRole('link', { name: /Chart/ })).toBeVisible();
    await expect(page.getByRole('link', { name: /Notification/ })).toBeVisible();
  });

  test('settings page has Dark and Light theme cards', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.getByText('Dark', { exact: true }).first()).toBeVisible();
    await expect(page.getByText('Light', { exact: true }).first()).toBeVisible();
  });

  test('settings page has Timezone selector', async ({ page }) => {
    await page.goto('/settings');
    await expect(page.getByText('Timezone')).toBeVisible();
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

    await page.getByRole('button', { name: 'Light', exact: false }).first().click();

    const theme = await page.evaluate(() =>
      document.documentElement.getAttribute('data-theme'),
    );
    expect(theme).toBe('light');
  });
});

test.describe('Navbar User Dropdown', () => {
  test.beforeEach(async ({ page }) => {
    await mockStockAPIs(page);
    await mockAuthSession(page, MOCK_AUTH_ME);
    await page.goto('/');
  });

  test('clicking avatar opens dropdown with user info', async ({ page }) => {
    const avatarBtn = page.getByRole('button', { name: 'T' });
    await avatarBtn.click();
    await expect(page.getByText('Test User')).toBeVisible();
    await expect(page.getByText('test@example.com')).toBeVisible();
  });

  test('dropdown has Logout button', async ({ page }) => {
    const avatarBtn = page.getByRole('button', { name: 'T' });
    await avatarBtn.click();
    await expect(page.getByRole('button', { name: /Logout/ })).toBeVisible();
  });

  test('clicking outside dropdown closes it', async ({ page }) => {
    const avatarBtn = page.getByRole('button', { name: 'T' });
    await avatarBtn.click();
    await expect(page.getByText('Test User')).toBeVisible();

    await page.mouse.click(200, 400);
    await expect(page.getByText('Test User')).not.toBeVisible();
  });

  test('dropdown uses glassmorphism (glass-dropdown class)', async ({ page }) => {
    const avatarBtn = page.getByRole('button', { name: 'T' });
    await avatarBtn.click();

    const dropdown = page.locator('.glass-dropdown');
    await expect(dropdown).toBeVisible();
  });
});
