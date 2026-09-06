import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isVwapAvailable, calculateVWAP } from './indicators.ts';

test('isVwapAvailable — intraday timeframes return true', () => {
    for (const tf of ['1m', '5m', '15m', '1h', '4h']) {
        assert.equal(isVwapAvailable(tf), true, `expected ${tf} to be available`);
    }
});

test('isVwapAvailable — daily+ timeframes return false', () => {
    for (const tf of ['1D', '1W', '1M']) {
        assert.equal(isVwapAvailable(tf), false, `expected ${tf} to be unavailable`);
    }
});

test('isVwapAvailable — unknown timeframe defaults to false', () => {
    assert.equal(isVwapAvailable('bogus'), false);
});

// bd:shotockviz-9z0 — strictNullChecks surfaced that Bar.high/low are optional
// but calculateVWAP computed (high + low + close) / 3 directly: one close-only
// bar made typicalPrice NaN, and the NaN then poisoned cumPV/VWAP for every
// remaining bar of that day. The fix falls back to close for a missing side.
test('calculateVWAP — close-only bar does not poison the day with NaN', () => {
    const t0 = 1_757_130_000; // arbitrary intraday unix-seconds base
    const bars = [
        { time: t0, high: 12, low: 8, close: 10, volume: 100 },
        { time: t0 + 60, close: 20, volume: 100 }, // no high/low — close-only bar
        { time: t0 + 120, high: 33, low: 27, close: 30, volume: 100 },
    ];
    const result = calculateVWAP(bars);
    assert.equal(result.length, 3);
    for (const point of result) {
        assert.ok(Number.isFinite(point.value), `VWAP value ${point.value} must be finite`);
    }
    // Independent worked example: typical prices 10, 20, 30 at equal volume →
    // cumulative VWAP 10, 15, 20.
    assert.equal(result[0].value, 10);
    assert.equal(result[1].value, 15);
    assert.equal(result[2].value, 20);
});

test('calculateVWAP — volume-weighted with full OHLC bars', () => {
    const t0 = 1_757_130_000;
    const bars = [
        { time: t0, high: 11, low: 9, close: 10, volume: 300 },  // typical 10
        { time: t0 + 60, high: 21, low: 19, close: 20, volume: 100 }, // typical 20
    ];
    const result = calculateVWAP(bars);
    // (10*300 + 20*100) / 400 = 12.5 — computed by hand, not by the code under test
    assert.equal(result[1].value, 12.5);
});
