/**
 * Backend health-check tests
 * These tests hit the real backend — no mocking.
 */
import { test, expect } from '@playwright/test';

test.describe('API Health', () => {
  test('GET /api/health returns 200 with status ok', async ({ request }) => {
    const res = await request.get('/api/health');
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body).toHaveProperty('status', 'ok');
  });

  test('GET /api/health responds within 3 seconds', async ({ request }) => {
    const start = Date.now();
    const res = await request.get('/api/health');
    const elapsed = Date.now() - start;
    expect(res.ok()).toBeTruthy();
    expect(elapsed).toBeLessThan(3000);
  });

  test('unknown route returns 404', async ({ request }) => {
    const res = await request.get('/api/no-such-endpoint-xyz');
    expect(res.status()).toBe(404);
  });
});
