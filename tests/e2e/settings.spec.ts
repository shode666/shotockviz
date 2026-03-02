/**
 * Settings modal + theme toggle tests
 * Covers: open from navbar dropdown, theme switch, dark/light persistence, close.
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
    // Sun or Moon icon button
    const themeBtn = page.getByRole('button').filter({ has: page.locator('svg') }).nth(0);
    await expect(page.locator('nav button[class*="rounded-lg"]').nth(0)).toBeVisible();
  });

  test('clicking theme toggle switches between dark and light', async ({ page }) => {
    // Get initial theme
    const initialTheme = await page.evaluate(() =>
      document.documentElement.getAttribute('data-theme'),
    );

    // Find and click theme toggle button (has Sun or Moon icon)
    const themeBtn = page.locator('nav').getByRole('button').filter({ has: page.locator('svg') }).last();
    // Actually find by checking for the sun/moon button specifically
    // It's the button before the auth section
    const navBtns = page.locator('nav button');
    // Click the theme toggle (look for the one that changes data-theme)
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

    // Theme should have changed
    if (initialTheme === 'dark') {
      expect(newTheme).toBe('light');
    } else {
      expect(newTheme).toBe('dark');
    }
  });

  test('theme persists after page reload', async ({ page }) => {
    // Set to light via localStorage
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

test.describe('Settings Modal — open/close', () => {
  test.beforeEach(async ({ page }) => {
    await mockStockAPIs(page);
    await mockAuthSession(page, MOCK_AUTH_ME);
    await page.goto('/');
  });

  test('opens settings modal from user dropdown', async ({ page }) => {
    // Wait for auth to resolve
    const avatarBtn = page.getByRole('button', { name: 'T' });
    await expect(avatarBtn).toBeVisible({ timeout: 5000 });
    await avatarBtn.click();

    // Settings button appears in dropdown
    const settingsBtn = page.getByRole('button', { name: /Settings/ });
    await expect(settingsBtn).toBeVisible();
    await settingsBtn.click();

    // Glass-panel modal should appear
    await expect(page.locator('.glass-panel').first()).toBeVisible();
    await expect(page.getByText('Settings').first()).toBeVisible();
  });

  test('settings modal has "Appearance" section', async ({ page }) => {
    const avatarBtn = page.getByRole('button', { name: 'T' });
    await avatarBtn.click();
    await page.getByRole('button', { name: /Settings/ }).click();
    await expect(page.getByText('Appearance')).toBeVisible();
  });

  test('settings modal has Dark and Light theme cards', async ({ page }) => {
    const avatarBtn = page.getByRole('button', { name: 'T' });
    await avatarBtn.click();
    await page.getByRole('button', { name: /Settings/ }).click();
    await expect(page.getByText('Dark').first()).toBeVisible();
    await expect(page.getByText('Light').first()).toBeVisible();
  });

  test('settings modal has Timezone selector', async ({ page }) => {
    const avatarBtn = page.getByRole('button', { name: 'T' });
    await avatarBtn.click();
    await page.getByRole('button', { name: /Settings/ }).click();
    await expect(page.getByText('Timezone')).toBeVisible();
    // Select should have Asia/Bangkok option
    const timezoneSelect = page.locator('select').first();
    await expect(timezoneSelect).toBeVisible();
  });

  test('settings modal has Chart Defaults section', async ({ page }) => {
    const avatarBtn = page.getByRole('button', { name: 'T' });
    await avatarBtn.click();
    await page.getByRole('button', { name: /Settings/ }).click();
    await expect(page.getByText('Chart Defaults').first()).toBeVisible();
  });

  test('clicking "ปิด" closes the settings modal', async ({ page }) => {
    const avatarBtn = page.getByRole('button', { name: 'T' });
    await avatarBtn.click();
    await page.getByRole('button', { name: /Settings/ }).click();
    await expect(page.locator('.glass-panel').first()).toBeVisible();

    await page.getByRole('button', { name: 'ปิด' }).click();
    await expect(page.locator('.glass-overlay').first()).not.toBeVisible();
  });

  test('clicking outside the modal closes it', async ({ page }) => {
    const avatarBtn = page.getByRole('button', { name: 'T' });
    await avatarBtn.click();
    await page.getByRole('button', { name: /Settings/ }).click();
    await expect(page.locator('.glass-overlay').first()).toBeVisible();

    // Click the overlay backdrop (not the panel)
    await page.mouse.click(10, 10);
    await expect(page.locator('.glass-overlay').first()).not.toBeVisible();
  });
});

test.describe('Settings Modal — theme switching', () => {
  test('clicking "Light" card in settings switches to light mode', async ({ page }) => {
    await mockStockAPIs(page);
    await mockAuthSession(page, MOCK_AUTH_ME);
    // Start in dark mode
    await page.addInitScript(() => {
      localStorage.setItem('theme', 'dark');
    });
    await page.goto('/');

    const avatarBtn = page.getByRole('button', { name: 'T' });
    await avatarBtn.click();
    await page.getByRole('button', { name: /Settings/ }).click();

    // Click Light card
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

  test('dropdown has Settings button', async ({ page }) => {
    const avatarBtn = page.getByRole('button', { name: 'T' });
    await avatarBtn.click();
    await expect(page.getByRole('button', { name: /Settings/ })).toBeVisible();
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

    // Click somewhere else
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
