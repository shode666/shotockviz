/**
 * Unit test — useWebSocket data_ready(quote) → bumpDataVersion bug fix.
 *
 * bd:ux-2026-09 carried-in bug: `data_ready` messages with data_type === 'quote'
 * must bump the shared dataVersion counter so `usePriceUpdates` (Sidebar) refetches
 * immediately instead of waiting for the next 60s poll.
 *
 * No test runner was installed for the frontend (no vitest/jest in package.json).
 * Per dev-gate "lightest option" — Node 24 ships a native test runner (`node --test`)
 * with built-in TypeScript stripping, so this needs zero new dependencies.
 * The decision logic itself lives in `./wsDataReady.ts`, split out of
 * `useWebSocket.ts` because that hook also imports `@/store/*` path aliases
 * that only Vite's bundler resolves — plain `node --test` cannot.
 * Run: `cd frontend && npm test` (== `node --test`).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { shouldBumpDataVersion } from './wsDataReady.ts';

test('shouldBumpDataVersion returns true for data_ready + quote', () => {
    assert.equal(
        shouldBumpDataVersion({ type: 'data_ready', data_type: 'quote', symbol: 'PTT.BK' }),
        true,
    );
});

test('shouldBumpDataVersion returns false for data_ready + non-quote data_type', () => {
    for (const data_type of ['history', 'fundamentals', 'dashboard']) {
        assert.equal(
            shouldBumpDataVersion({ type: 'data_ready', data_type, symbol: 'PTT.BK' }),
            false,
        );
    }
});

test('shouldBumpDataVersion returns false for non data_ready message types', () => {
    assert.equal(shouldBumpDataVersion({ type: 'alert_triggered', data_type: 'quote' }), false);
    assert.equal(shouldBumpDataVersion({ type: 'price_update', data_type: 'quote' }), false);
});

test('shouldBumpDataVersion is safe against missing/null payloads', () => {
    assert.equal(shouldBumpDataVersion({}), false);
    assert.equal(shouldBumpDataVersion(null), false);
    assert.equal(shouldBumpDataVersion(undefined), false);
});
