import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildCurveQualifications, hasCurveQualifications } from './curveQualifications.ts';

test('single_currency book with nothing excluded: no qualification at all', () => {
    const perf = { fx_basis: 'single_currency', fx_estimated: false, fx_unavailable_symbols: [], currency_conflict_symbols: [] };
    assert.deepEqual(buildCurveQualifications(perf), []);
    assert.equal(hasCurveQualifications(perf), false);
});

test('null/undefined input: no qualification', () => {
    assert.deepEqual(buildCurveQualifications(null), []);
    assert.deepEqual(buildCurveQualifications(undefined), []);
    assert.equal(hasCurveQualifications(null), false);
});

test('constant_current_rate: states the basis, not currency return', () => {
    const perf = { fx_basis: 'constant_current_rate', fx_estimated: false, fx_unavailable_symbols: [], currency_conflict_symbols: [] };
    const quals = buildCurveQualifications(perf);
    assert.equal(quals.length, 1);
    assert.equal(quals[0].key, 'curve-constant-rate');
    assert.equal(quals[0].tone, 'info');
    assert.match(quals[0].text, /ไม่ใช่ผลตอบแทนจากค่าเงิน/);
    assert.doesNotMatch(quals[0].text, /ประมาณการ/);
});

test('constant_current_rate + fx_estimated: also flags the rate as an estimate', () => {
    const perf = { fx_basis: 'constant_current_rate', fx_estimated: true, fx_unavailable_symbols: [], currency_conflict_symbols: [] };
    const quals = buildCurveQualifications(perf);
    assert.equal(quals.length, 1);
    assert.match(quals[0].text, /ประมาณการ/);
});

test('currency_conflict_symbols named even when basis stays single_currency', () => {
    // backend/services/portfolio_service.py curve_fx_plan(): a currency-conflict
    // symbol `continue`s before ever touching `plan.basis` — so an otherwise
    // all-THB book with one conflicting symbol still reports single_currency.
    const perf = { fx_basis: 'single_currency', fx_estimated: false, fx_unavailable_symbols: [], currency_conflict_symbols: ['PTT'] };
    const quals = buildCurveQualifications(perf);
    assert.equal(quals.length, 1);
    assert.equal(quals[0].key, 'curve-currency-conflict');
    assert.equal(quals[0].tone, 'error');
    assert.match(quals[0].text, /PTT/);
});

test('fx_unavailable_symbols named', () => {
    const perf = { fx_basis: 'constant_current_rate', fx_estimated: false, fx_unavailable_symbols: ['XAU'], currency_conflict_symbols: [] };
    const quals = buildCurveQualifications(perf);
    assert.equal(quals.length, 2);
    assert.equal(quals[0].key, 'curve-fx-unavailable');
    assert.match(quals[0].text, /XAU/);
});

test('ordering is worst-first: conflict, then fx-unavailable, then constant-rate', () => {
    const perf = {
        fx_basis: 'constant_current_rate',
        fx_estimated: false,
        fx_unavailable_symbols: ['XAU'],
        currency_conflict_symbols: ['PTT'],
    };
    const quals = buildCurveQualifications(perf);
    assert.deepEqual(quals.map((q) => q.key), ['curve-currency-conflict', 'curve-fx-unavailable', 'curve-constant-rate']);
});

test('multiple symbols in one category are joined, not one qualification per symbol', () => {
    const perf = { fx_basis: 'single_currency', fx_estimated: false, fx_unavailable_symbols: [], currency_conflict_symbols: ['PTT', 'AOT'] };
    const quals = buildCurveQualifications(perf);
    assert.equal(quals.length, 1);
    assert.match(quals[0].text, /PTT, AOT/);
});
