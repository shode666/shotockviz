import { test } from 'node:test';
import assert from 'node:assert/strict';
import { isVwapAvailable } from './indicators.ts';

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
