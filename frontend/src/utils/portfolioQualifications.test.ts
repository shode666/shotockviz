import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildQualifications, hasQualifications } from './portfolioQualifications.ts';

// bd:shotockviz-pxo — the qualification must exist, be ordered worst-first, and
// say "excluded" rather than leave the user to read 0 as a value.

const keys = (a: Parameters<typeof buildQualifications>[0]) =>
    buildQualifications(a).map((q) => q.key);

test('a clean, fully priced THB book is qualified by nothing', () => {
    assert.deepEqual(
        keys({
            holdings: [{ symbol: 'PTT.BK', current_price: 38 }],
            has_pending_prices: false,
            fx_rates: [],
        }),
        [],
    );
    assert.equal(hasQualifications({ holdings: [{ symbol: 'PTT.BK', current_price: 38 }] }), false);
});

test('null/undefined analytics does not throw and qualifies nothing', () => {
    assert.deepEqual(buildQualifications(null), []);
    assert.deepEqual(buildQualifications(undefined), []);
    assert.equal(hasQualifications(null), false);
});

test('the all-unpriced book (bd:shotockviz-2w8) is explained, and names the symbols', () => {
    const q = buildQualifications({
        holdings: [
            { symbol: 'PTT.BK', current_price: null },
            { symbol: 'KBANK.BK', current_price: null },
        ],
        has_pending_prices: true,
    });
    assert.equal(q.length, 1);
    assert.equal(q[0].key, 'pending-prices');
    assert.match(q[0].text, /PTT\.BK, KBANK\.BK/);
    // The reading the zeros must not be given.
    assert.match(q[0].text, /ไม่ได้แปลว่ามูลค่าเป็น 0/);
    assert.match(q[0].text, /ไม่รวมรายการเหล่านี้/);
});

test('has_pending_prices without any unpriced row says nothing (no empty banner)', () => {
    assert.deepEqual(
        keys({ holdings: [{ symbol: 'PTT.BK', current_price: 38 }], has_pending_prices: true }),
        [],
    );
});

test('a currency conflict outranks a pending price, and is not worded as a delay', () => {
    const q = buildQualifications({
        currency_conflict_symbols: ['NVDA'],
        holdings: [
            { symbol: 'NVDA', current_price: null, currency_conflict: true },
            { symbol: 'PTT.BK', current_price: null },
        ],
        has_pending_prices: true,
    });
    assert.deepEqual(q.map((x) => x.key), ['currency-conflict', 'pending-prices']);
    assert.equal(q[0].tone, 'error');
    // A conflicted symbol is broken, not loading — it must not also appear in
    // the "waiting for a price" sentence.
    assert.doesNotMatch(q[1].text, /NVDA/);
    assert.match(q[1].text, /PTT\.BK/);
    assert.doesNotMatch(q[0].text, /อัปเดตอัตโนมัติ/);
});

test('a currency with no rate is reported as excluded, not added raw', () => {
    const q = buildQualifications({ fx_unavailable_symbols: ['NVDA'] });
    assert.deepEqual(q.map((x) => x.key), ['fx-unavailable']);
    assert.match(q[0].text, /ไม่ถูกรวมในยอดรวม/);
});

test('unknown FX return is stated as unknown, and only when there is FX at all', () => {
    assert.deepEqual(keys({ fx_rates: [{}], fx_pl: null }), ['fx-pl-unknown']);
    // fx_pl of 0 on a THB-only book is a fact, not a missing value.
    assert.deepEqual(keys({ fx_rates: [{}], fx_pl: 0 }), []);
    // No FX in the book -> no FX sentence, even if fx_pl came back null.
    assert.deepEqual(keys({ fx_rates: [], fx_pl: null }), []);
});

test('cost converted at today\'s rate is disclosed as its own line', () => {
    assert.deepEqual(
        keys({ fx_rates: [{}], fx_pl: 1000, cost_basis_estimated: true }),
        ['cost-basis-estimated'],
    );
});

test('full ordering: worst first, every item keyed once', () => {
    const q = buildQualifications({
        currency_conflict_symbols: ['AAPL'],
        holdings: [
            { symbol: 'AAPL', current_price: null, currency_conflict: true },
            { symbol: 'PTT.BK', current_price: null },
        ],
        has_pending_prices: true,
        fx_unavailable_symbols: ['EURO.X'],
        fx_rates: [{}],
        fx_pl: null,
        cost_basis_estimated: true,
    });
    assert.deepEqual(q.map((x) => x.key), [
        'currency-conflict',
        'pending-prices',
        'fx-unavailable',
        'fx-pl-unknown',
        'cost-basis-estimated',
    ]);
    assert.equal(new Set(q.map((x) => x.key)).size, q.length);
});

test('a book with only FX rates to disclose still renders the block', () => {
    assert.deepEqual(keys({ fx_rates: [{}], fx_pl: 500 }), []);
    assert.equal(hasQualifications({ fx_rates: [{}], fx_pl: 500 }), true);
});
