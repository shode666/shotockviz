/**
 * Unit tests — parseSymbol crypto pair handling (bd:features-2026-09 F1).
 * Run: `node --test src/utils/formatters.test.ts`, same runner
 * convention as src/utils/srLevelColor.test.ts.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { parseSymbol } from './formatters.ts';

test('parseSymbol classifies BTC-USD as CRYPTO, keeps full pair as display', () => {
    assert.deepEqual(parseSymbol('BTC-USD'), {
        display: 'BTC-USD',
        market: 'CRYPTO',
        suffix: '',
    });
});

test('parseSymbol classifies ETH-USD as CRYPTO, keeps full pair as display', () => {
    assert.deepEqual(parseSymbol('ETH-USD'), {
        display: 'ETH-USD',
        market: 'CRYPTO',
        suffix: '',
    });
});

test('parseSymbol leaves AAPL unchanged (US)', () => {
    assert.deepEqual(parseSymbol('AAPL'), {
        display: 'AAPL',
        market: 'US',
        suffix: '',
    });
});

test('parseSymbol leaves ADVANC.BK unchanged (SET)', () => {
    assert.deepEqual(parseSymbol('ADVANC.BK'), {
        display: 'ADVANC',
        market: 'SET',
        suffix: '.BK',
    });
});

test('parseSymbol does NOT classify GLD (gold ETF) as CRYPTO', () => {
    assert.deepEqual(parseSymbol('GLD'), {
        display: 'GLD',
        market: 'US',
        suffix: '',
    });
});

test('parseSymbol leaves SCBS&P500 unchanged (FUND)', () => {
    assert.deepEqual(parseSymbol('SCBS&P500'), {
        display: 'SCBS&P500',
        market: 'FUND',
        suffix: '',
    });
});

test('parseSymbol does NOT classify BRK-B (class-share ticker) as CRYPTO', () => {
    assert.deepEqual(parseSymbol('BRK-B'), {
        display: 'BRK-B',
        market: 'US',
        suffix: '',
    });
});
