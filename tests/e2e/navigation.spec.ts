/**
 * Navigation tests
 * Verifies that the navbar links and sidebar navigation work correctly.
 */
import { test, expect } from '@playwright/test';
import { mockStockAPIs } from './helpers/mocks';

test.describe('Navbar navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/');
  });

  test('navbar shows all 5 nav items', async ({ page }) => {
    const navLinks = ['Chart', 'Screener', 'Portfolio', 'Alerts', 'News'];
    for (const label of navLinks) {
      await expect(page.getByRole('link', { name: label, exact: true })).toBeVisible();
    }
  });

  test('navigates to Screener page', async ({ page }) => {
    await page.getByRole('link', { name: 'Screener', exact: true }).click();
    await expect(page).toHaveURL('/screener');
    await expect(page.getByText('Stock Screener')).toBeVisible();
  });

  test('navigates to Portfolio page', async ({ page }) => {
    await page.getByRole('link', { name: 'Portfolio', exact: true }).click();
    await expect(page).toHaveURL('/portfolio');
  });

  test('navigates to Alerts page', async ({ page }) => {
    await page.getByRole('link', { name: 'Alerts', exact: true }).click();
    await expect(page).toHaveURL('/alerts');
  });

  test('navigates to News page', async ({ page }) => {
    await page.getByRole('link', { name: 'News', exact: true }).click();
    await expect(page).toHaveURL('/news');
  });

  test('Chart link navigates back to home', async ({ page }) => {
    // Go to screener first
    await page.goto('/screener');
    await mockStockAPIs(page); // re-apply after navigation
    await page.getByRole('link', { name: 'Chart', exact: true }).click();
    await expect(page).toHaveURL('/');
  });

  test('Logo / brand renders in navbar', async ({ page }) => {
    // "Viz" is part of the ShotockViz brand in the navbar
    await expect(page.getByText('Viz').first()).toBeVisible();
  });

  test('search bar is visible in navbar', async ({ page }) => {
    await expect(page.getByText(/ค้นหา PTT, AAPL/)).toBeVisible();
  });
});

test.describe('Sidebar navigation', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
    await page.goto('/');
  });

  test('clicking NVDA in sidebar updates selected stock', async ({ page }) => {
    // NVDA is in DEFAULT_WATCHLIST
    const nvdaBtn = page.getByRole('button').filter({ hasText: 'NVDA' }).first();
    await nvdaBtn.click();

    // Toolbar should now show NVDA as the selected symbol
    await expect(page.getByText('NVDA').first()).toBeVisible();
    await expect(page).toHaveURL('/');
  });

  test('sidebar "+ เพิ่มหุ้น" button redirects to login when not authenticated', async ({ page }) => {
    const addBtn = page.getByRole('button', { name: '+ เพิ่มหุ้น' });
    await addBtn.click();
    await expect(page).toHaveURL('/login');
  });
});

test.describe('Direct URL access', () => {
  test.beforeEach(async ({ page }) => {
    await page.addInitScript(() => {
      localStorage.removeItem('access_token');
      localStorage.removeItem('refresh_token');
    });
    await mockStockAPIs(page);
  });

  test('can load /screener directly', async ({ page }) => {
    await page.goto('/screener');
    await expect(page.getByText('Stock Screener')).toBeVisible();
  });

  test('can load /login directly', async ({ page }) => {
    await page.goto('/login');
    await expect(page.getByText('Stock Analysis Platform')).toBeVisible();
  });

  test('can load / directly', async ({ page }) => {
    await page.goto('/');
    await expect(page.getByText('PTT.BK').first()).toBeVisible();
  });

  test('can load /portfolio directly', async ({ page }) => {
    await page.goto('/portfolio');
    await expect(page).toHaveURL('/portfolio');
  });

  test('can load /alerts directly', async ({ page }) => {
    await page.goto('/alerts');
    await expect(page).toHaveURL('/alerts');
  });

  test('can load /news directly', async ({ page }) => {
    await page.goto('/news');
    await expect(page).toHaveURL('/news');
  });
});
