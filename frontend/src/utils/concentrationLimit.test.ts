import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    isValidConcentrationLimitPct,
    hasConcentrationBreach,
    notCheckedSentence,
    concentrationLimitStorageKey,
    MIN_CONCENTRATION_LIMIT_PCT,
    MAX_CONCENTRATION_LIMIT_PCT,
    DEFAULT_CONCENTRATION_LIMIT_PCT,
} from './concentrationLimit.ts';

// bd:shotockviz-649 — the breach math itself lives once, server-side
// (services/portfolio_service.py::build_concentration_check); this file's
// job is validation, storage, and the "not_checked" sentence, so that is
// what is under test here.

// ─────────────────────────────────────────────────────────────────────────────
// isValidConcentrationLimitPct — boundaries, not just "is it a number"
// ─────────────────────────────────────────────────────────────────────────────

test('a limit inside the bounds is valid', () => {
    assert.equal(isValidConcentrationLimitPct(DEFAULT_CONCENTRATION_LIMIT_PCT), true);
    assert.equal(isValidConcentrationLimitPct(50), true);
});

test('the bounds themselves are valid — inclusive, not exclusive', () => {
    assert.equal(isValidConcentrationLimitPct(MIN_CONCENTRATION_LIMIT_PCT), true);
    assert.equal(isValidConcentrationLimitPct(MAX_CONCENTRATION_LIMIT_PCT), true);
});

test('one step outside either bound is invalid', () => {
    assert.equal(isValidConcentrationLimitPct(MIN_CONCENTRATION_LIMIT_PCT - 1), false);
    assert.equal(isValidConcentrationLimitPct(MAX_CONCENTRATION_LIMIT_PCT + 1), false);
});

test('100 is never a valid limit — a single name is always <= 100% of its own book', () => {
    assert.equal(isValidConcentrationLimitPct(100), false);
});

test('non-finite input is invalid, not silently coerced', () => {
    assert.equal(isValidConcentrationLimitPct(NaN), false);
    assert.equal(isValidConcentrationLimitPct(Infinity), false);
    assert.equal(isValidConcentrationLimitPct(-Infinity), false);
});

// ─────────────────────────────────────────────────────────────────────────────
// hasConcentrationBreach — a point-in-time read, never sticky
// ─────────────────────────────────────────────────────────────────────────────

test('no breaches is not a breach', () => {
    assert.equal(hasConcentrationBreach({ breaches: [] }), false);
    assert.equal(hasConcentrationBreach({}), false);
    assert.equal(hasConcentrationBreach(null), false);
    assert.equal(hasConcentrationBreach(undefined), false);
});

test('one breach is a breach', () => {
    assert.equal(
        hasConcentrationBreach({
            breaches: [
                { symbol: 'PTT.BK', weight_pct: 80, limit_pct: 25, excess_pct: 55, value_base: 80000, trim_value_base: 73333.33 },
            ],
        }),
        true,
    );
});

// ─────────────────────────────────────────────────────────────────────────────
// notCheckedSentence — rule 1/5 collision: an excluded position is neither
// "safe" nor "breached", and this is where that gets said out loud.
// ─────────────────────────────────────────────────────────────────────────────

test('a fully-checked book says nothing extra', () => {
    assert.equal(notCheckedSentence({ not_checked: [] }), null);
    assert.equal(notCheckedSentence({}), null);
    assert.equal(notCheckedSentence(null), null);
});

test('excluded positions are grouped by reason and named, in Thai', () => {
    const s = notCheckedSentence({
        not_checked: [
            { symbol: 'KBANK.BK', reason: 'unpriced' },
            { symbol: 'NVDA', reason: 'currency_conflict' },
            { symbol: 'PTT.BK', reason: 'unpriced' },
        ],
    });
    assert.ok(s);
    assert.match(s!, /KBANK\.BK, PTT\.BK \(ยังไม่มีราคาล่าสุด\)/);
    assert.match(s!, /NVDA \(สกุลเงินไม่ตรงกัน\)/);
    // The reading the user must never have to guess: excluded is not "safe".
    assert.match(s!, /ไม่ได้แปลว่าอยู่ในเกณฑ์ปลอดภัย/);
});

test('every backend reason has Thai wording, and an unknown one is not swallowed', () => {
    for (const reason of ['unpriced', 'fx_unavailable', 'currency_conflict', 'unstatable']) {
        const s = notCheckedSentence({ not_checked: [{ symbol: 'X', reason }] });
        assert.ok(s && !s.includes(reason), `reason "${reason}" rendered untranslated`);
    }
    const unknown = notCheckedSentence({ not_checked: [{ symbol: 'X', reason: 'brand_new' }] });
    assert.match(unknown!, /brand_new/);
});

// ─────────────────────────────────────────────────────────────────────────────
// Storage key — namespaced per user, never shared across accounts
// ─────────────────────────────────────────────────────────────────────────────

test('the storage key is namespaced per user id', () => {
    assert.notEqual(concentrationLimitStorageKey(1), concentrationLimitStorageKey(2));
    assert.equal(concentrationLimitStorageKey(1), concentrationLimitStorageKey(1));
});
