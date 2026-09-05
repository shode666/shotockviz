import { test } from 'node:test';
import assert from 'node:assert/strict';
import { formatLastUpdate, getLastQuoteTimestamp, nextLastUpdate, type LastUpdateState } from './statusBar.ts';

test('formatLastUpdate: null timestamp (no data_ready yet this session) returns em-dash', () => {
    assert.equal(formatLastUpdate(null, Date.now()), '—');
});

test('formatLastUpdate: formats a real timestamp as HH:MM:SS, not the current wall clock', () => {
    const dataReadyAt = new Date('2026-09-05T03:04:05Z').getTime();
    const laterNow = dataReadyAt + 60_000; // 1 minute after the data arrived
    const result = formatLastUpdate(dataReadyAt, laterNow);
    assert.equal(result, new Date(dataReadyAt).toLocaleTimeString('en-GB', { hour12: false }));
    // Must reflect the data timestamp, not `now`
    assert.notEqual(result, new Date(laterNow).toLocaleTimeString('en-GB', { hour12: false }));
});

// bd:ui-honesty-2026-09 F3 r2 (03b-bella-spec-r2-F3.md) — getLastQuoteTimestamp

test('getLastQuoteTimestamp: null payload returns null', () => {
    assert.equal(getLastQuoteTimestamp(null, 'NVDA'), null);
});

test('getLastQuoteTimestamp: data_type "history", symbol matches selected -> null (Chris regression)', () => {
    const payload = { data_type: 'history', symbol: 'NVDA', _key: 123 };
    assert.equal(getLastQuoteTimestamp(payload, 'NVDA'), null);
});

test('getLastQuoteTimestamp: data_type "fundamentals", symbol matches selected -> null', () => {
    const payload = { data_type: 'fundamentals', symbol: 'NVDA', _key: 123 };
    assert.equal(getLastQuoteTimestamp(payload, 'NVDA'), null);
});

test('getLastQuoteTimestamp: data_type "quote", symbol matches selected -> returns _key', () => {
    const payload = { data_type: 'quote', symbol: 'NVDA', _key: 123 };
    assert.equal(getLastQuoteTimestamp(payload, 'NVDA'), 123);
});

test('getLastQuoteTimestamp: data_type "quote", symbol "*" (broadcast) -> returns _key regardless of selected', () => {
    const payload = { data_type: 'quote', symbol: '*', _key: 456 };
    assert.equal(getLastQuoteTimestamp(payload, 'AAPL'), 456);
});

test('getLastQuoteTimestamp: data_type "quote", different real ticker than selected -> null', () => {
    const payload = { data_type: 'quote', symbol: 'AAPL', _key: 789 };
    assert.equal(getLastQuoteTimestamp(payload, 'NVDA'), null);
});

test('getLastQuoteTimestamp: data_type "quote", symbol matches, no _key -> null (defensive)', () => {
    const payload = { data_type: 'quote', symbol: 'NVDA' };
    assert.equal(getLastQuoteTimestamp(payload, 'NVDA'), null);
});

// bd:ui-honesty-2026-09 F3 r3 (Quinn's regression: a non-qualifying message
// must leave the prior remembered value UNCHANGED, not reset it to null) —
// nextLastUpdate

test('nextLastUpdate: qualifying quote for the selected symbol -> value advances', () => {
    const prev: LastUpdateState = { symbol: 'NVDA', timestamp: null };
    const result = nextLastUpdate(prev, { data_type: 'quote', symbol: 'NVDA', _key: 100 }, 'NVDA');
    assert.deepEqual(result, { symbol: 'NVDA', timestamp: 100 });
});

test('nextLastUpdate: non-qualifying same-symbol history after a qualifying value -> UNCHANGED (Quinn regression)', () => {
    const prev: LastUpdateState = { symbol: 'NVDA', timestamp: 100 };
    const result = nextLastUpdate(prev, { data_type: 'history', symbol: 'NVDA', _key: 200 }, 'NVDA');
    assert.deepEqual(result, { symbol: 'NVDA', timestamp: 100 });
});

test('nextLastUpdate: non-qualifying other-symbol quote after a qualifying value -> UNCHANGED', () => {
    const prev: LastUpdateState = { symbol: 'NVDA', timestamp: 100 };
    const result = nextLastUpdate(prev, { data_type: 'quote', symbol: 'AAPL', _key: 300 }, 'NVDA');
    assert.deepEqual(result, { symbol: 'NVDA', timestamp: 100 });
});

test('nextLastUpdate: symbol change with no qualifying message for the new symbol -> resets to null', () => {
    const prev: LastUpdateState = { symbol: 'NVDA', timestamp: 100 };
    const result = nextLastUpdate(prev, { data_type: 'quote', symbol: 'AAPL', _key: 300 }, 'TSLA');
    assert.deepEqual(result, { symbol: 'TSLA', timestamp: null });
});

test('nextLastUpdate: full sequence — qualifying, then same-symbol non-qualifying x2 (unchanged), then symbol change (reset)', () => {
    let state: LastUpdateState = { symbol: 'NVDA', timestamp: null };

    state = nextLastUpdate(state, { data_type: 'quote', symbol: 'NVDA', _key: 100 }, 'NVDA');
    assert.deepEqual(state, { symbol: 'NVDA', timestamp: 100 });

    state = nextLastUpdate(state, { data_type: 'history', symbol: 'NVDA', _key: 200 }, 'NVDA');
    assert.deepEqual(state, { symbol: 'NVDA', timestamp: 100 });

    state = nextLastUpdate(state, { data_type: 'quote', symbol: 'AAPL', _key: 300 }, 'NVDA');
    assert.deepEqual(state, { symbol: 'NVDA', timestamp: 100 });

    state = nextLastUpdate(state, { data_type: 'quote', symbol: 'AAPL', _key: 300 }, 'TSLA');
    assert.deepEqual(state, { symbol: 'TSLA', timestamp: null });
});

test('nextLastUpdate: symbol change where the same payload already qualifies for the NEW symbol (broadcast) -> applied immediately, no dropped frame', () => {
    const prev: LastUpdateState = { symbol: 'NVDA', timestamp: 100 };
    const result = nextLastUpdate(prev, { data_type: 'quote', symbol: '*', _key: 400 }, 'TSLA');
    assert.deepEqual(result, { symbol: 'TSLA', timestamp: 400 });
});

test('nextLastUpdate: null payload, same symbol -> UNCHANGED', () => {
    const prev: LastUpdateState = { symbol: 'NVDA', timestamp: 100 };
    const result = nextLastUpdate(prev, null, 'NVDA');
    assert.deepEqual(result, { symbol: 'NVDA', timestamp: 100 });
});
