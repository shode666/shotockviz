import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatCachedAge } from './cachedValueAge.ts';

// bd:shotockviz-f14 — "no cached number says how old it is". Generic
// as-of-age formatter for cached numbers whose refresh cadence is HOURS,
// not the price field's minutes (bd:shotockviz-09j's statusBar.ts already
// owns that one, with amber/red thresholds tuned to price_fetcher's 1-min
// cadence). This module does NOT invent a fresh/stale/very-stale traffic
// light for a cadence nobody has specified thresholds for (Bella's
// AMBER/RED sign-off in statusBar.ts is still open even for the price
// case) — it only ever states the real, literal age, or says unknown.

test('formatCachedAge: no ts -> unknown, does not fabricate an age', () => {
    assert.deepEqual(formatCachedAge(null, Date.now()), { known: false, label: 'ไม่ทราบเวลาข้อมูล' });
    assert.deepEqual(formatCachedAge(undefined, Date.now()), { known: false, label: 'ไม่ทราบเวลาข้อมูล' });
});

test('formatCachedAge: under 1 minute reads "just now"', () => {
    const now = 1_800_000_000_000;
    const ts = now / 1000; // 0s old
    assert.deepEqual(formatCachedAge(ts, now), { known: true, label: 'เมื่อครู่นี้' });
});

test('formatCachedAge: minutes only, rounds down, no hours shown under 1h', () => {
    const now = 1_800_000_000_000;
    const ts = now / 1000 - 45 * 60; // 45 min old
    assert.deepEqual(formatCachedAge(ts, now), { known: true, label: '45 นาทีที่แล้ว' });
});

test('formatCachedAge: exactly 60 minutes rolls over to "1 ชม."', () => {
    const now = 1_800_000_000_000;
    const ts = now / 1000 - 60 * 60;
    assert.deepEqual(formatCachedAge(ts, now), { known: true, label: '1 ชม.ที่แล้ว' });
});

test('formatCachedAge: hours + leftover minutes both shown', () => {
    const now = 1_800_000_000_000;
    const ts = now / 1000 - (3 * 3600 + 20 * 60); // 3h20m old
    assert.deepEqual(formatCachedAge(ts, now), { known: true, label: '3 ชม. 20 นาทีที่แล้ว' });
});

test('formatCachedAge: negative age (clock skew) clamps to "just now", does not throw or go negative', () => {
    const now = 1_800_000_000_000;
    const ts = now / 1000 + 5; // ts is 5s in the "future" relative to now
    assert.deepEqual(formatCachedAge(ts, now), { known: true, label: 'เมื่อครู่นี้' });
});
