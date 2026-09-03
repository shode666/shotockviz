/**
 * Backend health-check tests
 * These tests hit the real backend — no mocking.
 */
import { test, expect } from '@playwright/test';

test.describe('API Health', () => {
  test('GET /api/health returns 200 with the enveloped {data,meta} shape', async ({ request }) => {
    // bd:deps-2026-09 iter1 (CHRIS-12/Q-6, AC-B7) — was asserting a
    // top-level `status: 'ok'` key that never existed even before this
    // migration's S2 envelope flip: api/routes/system.py:91's handler has
    // ALWAYS returned response_model=BaseResponse[dict], i.e.
    // {data: {database, redis, celery}, meta: {...}} — there is no
    // top-level `status` field on this endpoint, documented in its own
    // docstring. This assertion silently no-op'd (never actually ran
    // against a live backend before Quinn's Phase 3b review — see
    // 00-oliver-discover.md:29 / 15-quinn-review.md Finding Q-6) so the
    // mismatch went uncaught until now.
    const res = await request.get('/api/health');
    expect(res.ok()).toBeTruthy();
    const body = await res.json();
    expect(body).toHaveProperty('data');
    expect(body).toHaveProperty('meta');
    expect(body.data).toHaveProperty('database');
    expect(body.data).toHaveProperty('redis');
    expect(body.data).toHaveProperty('celery');
    expect(body.data.database).toBe('ok');
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
