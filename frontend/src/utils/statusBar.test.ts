import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatAgeThai, getPriceFreshness } from './statusBar.ts';

// bd:shotockviz-09j — real price age from server `ts`, replacing the
// data_ready-derived path (ADR-UH-001/001a) that always read "—".

test('formatAgeThai: under 1 minute reads "just now"', () => {
    assert.equal(formatAgeThai(0), 'เมื่อครู่นี้');
    assert.equal(formatAgeThai(59_000), 'เมื่อครู่นี้');
});

test('formatAgeThai: rounds down to whole minutes', () => {
    assert.equal(formatAgeThai(60_000), '1 นาทีที่แล้ว');
    assert.equal(formatAgeThai(119_000), '1 นาทีที่แล้ว');
    assert.equal(formatAgeThai(4 * 60_000), '4 นาทีที่แล้ว');
});

test('formatAgeThai: negative age (clock skew) clamps to "just now", does not throw or go negative', () => {
    assert.equal(formatAgeThai(-5_000), 'เมื่อครู่นี้');
});

test('getPriceFreshness: no ts yet this session -> unknown / em-dash, regardless of market state', () => {
    assert.deepEqual(getPriceFreshness(null, Date.now(), true), { tone: 'unknown', label: '—' });
    assert.deepEqual(getPriceFreshness(undefined, Date.now(), null), { tone: 'unknown', label: '—' });
});

test('getPriceFreshness: fresh (<=2min), market open -> fresh tone, age label', () => {
    const now = 1_800_000_000_000;
    const ts = now / 1000 - 90; // 90s old
    assert.deepEqual(getPriceFreshness(ts, now, true), { tone: 'fresh', label: '1 นาทีที่แล้ว' });
});

test('getPriceFreshness: exactly at the amber boundary (2min) still reads fresh', () => {
    const now = 1_800_000_000_000;
    const ts = now / 1000 - 120;
    assert.equal(getPriceFreshness(ts, now, true).tone, 'fresh');
});

test('getPriceFreshness: just past amber boundary, market open -> stale (amber)', () => {
    const now = 1_800_000_000_000;
    const ts = now / 1000 - 121;
    const result = getPriceFreshness(ts, now, true);
    assert.equal(result.tone, 'stale');
    assert.equal(result.label, '2 นาทีที่แล้ว');
});

test('getPriceFreshness: 4 minutes old, market open -> stale, not red (the cited "normal" range must not cry wolf)', () => {
    const now = 1_800_000_000_000;
    const ts = now / 1000 - 4 * 60;
    assert.equal(getPriceFreshness(ts, now, true).tone, 'stale');
});

test('getPriceFreshness: just past the 6-minute red boundary, market open -> very-stale (red)', () => {
    const now = 1_800_000_000_000;
    const ts = now / 1000 - (6 * 60 + 1);
    const result = getPriceFreshness(ts, now, true);
    assert.equal(result.tone, 'very-stale');
    assert.equal(result.label, '6 นาทีที่แล้ว');
});

test('getPriceFreshness: exactly at the 6-minute boundary is still stale (amber), not yet red', () => {
    const now = 1_800_000_000_000;
    const ts = now / 1000 - 6 * 60;
    assert.equal(getPriceFreshness(ts, now, true).tone, 'stale');
});

test('getPriceFreshness: stale AND market closed -> market-closed overrides amber, not just red', () => {
    const now = 1_800_000_000_000;
    const ts = now / 1000 - 3 * 60; // would be amber if the market were open
    assert.deepEqual(getPriceFreshness(ts, now, false), { tone: 'market-closed', label: 'ตลาดปิด' });
});

test('getPriceFreshness: very stale AND market closed -> market-closed overrides red (a stale price at 02:00 on a closed SET symbol is not a fault)', () => {
    const now = 1_800_000_000_000;
    const ts = now / 1000 - 5 * 3600; // 5 hours old
    assert.deepEqual(getPriceFreshness(ts, now, false), { tone: 'market-closed', label: 'ตลาดปิด' });
});

test('getPriceFreshness: fresh AND market closed -> still fresh, no need to override something that is not alarming', () => {
    const now = 1_800_000_000_000;
    const ts = now / 1000 - 30;
    assert.equal(getPriceFreshness(ts, now, false).tone, 'fresh');
});

test('getPriceFreshness: unknown market (marketOpen null, e.g. FUND/CRYPTO) -> normal thresholds apply, no closed override', () => {
    const now = 1_800_000_000_000;
    const ts = now / 1000 - 10 * 60; // 10 min old
    const result = getPriceFreshness(ts, now, null);
    assert.equal(result.tone, 'very-stale');
});
