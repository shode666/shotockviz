import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    groupAllocation,
    donutSegments,
    exclusionSentence,
    hasAllocation,
    sliceColor,
    ALLOCATION_TOP_N,
    type AllocationSliceInput,
} from './allocation.ts';

// bd:shotockviz-916 — the two ways an allocation chart lies:
//   1. its arcs do not cover what it says the total is;
//   2. it silently drops the positions the totals excluded.
// Everything below is one of those two.

const slice = (
    symbol: string,
    value_base: number,
    extra: Partial<AllocationSliceInput> = {},
): AllocationSliceInput => ({ symbol, value_base, ...extra });

test('slices are drawn heaviest first regardless of payload order', () => {
    const g = groupAllocation({ slices: [slice('A', 10), slice('C', 100), slice('B', 50)] });
    assert.deepEqual(g.map((s) => s.label), ['C', 'B', 'A']);
});

test('weights describe the ring that is drawn, and sum to 100', () => {
    const g = groupAllocation({ slices: [slice('A', 40_000), slice('B', 12_000)] });
    assert.equal(g.length, 2);
    assert.equal(Math.round(g[0].weight_pct * 100) / 100, 76.92);
    assert.equal(Math.round(g[1].weight_pct * 100) / 100, 23.08);
    assert.ok(Math.abs(g.reduce((s, x) => s + x.weight_pct, 0) - 100) < 1e-9);
});

test('arcs cover the whole circle exactly, with no gap at the seam', () => {
    const g = groupAllocation({ slices: [slice('A', 1), slice('B', 2), slice('C', 3)] });
    const segs = donutSegments(g);
    const covered = segs.reduce((sum, s) => sum + s.dash, 0);
    assert.ok(Math.abs(covered - 100) < 1e-9, `ring covers ${covered}, not 100`);
    // Each arc starts where the previous one ended.
    assert.equal(segs[0].offset, 0);
    assert.ok(Math.abs(segs[1].offset + segs[0].dash) < 1e-9);
    assert.ok(Math.abs(segs[2].offset + segs[0].dash + segs[1].dash) < 1e-9);
    // dash + gap is one full turn for every segment.
    for (const s of segs) assert.ok(Math.abs(s.dash + s.gap - 100) < 1e-9);
});

test('a single holding is a closed ring, not a 100%-minus-epsilon arc', () => {
    const segs = donutSegments(groupAllocation({ slices: [slice('ONLY', 123.45)] }));
    assert.deepEqual(segs, [{ key: 'ONLY', dash: 100, gap: 0, offset: 0 }]);
});

test('geometry uses value, not the rounded weight the backend sent', () => {
    // Three equal thirds: rounded weights would be 33.33 each and leave 0.01 of
    // the ring undrawn. The values must be what is divided.
    const g = groupAllocation({
        slices: [
            slice('A', 100, { weight_pct: 33.33 }),
            slice('B', 100, { weight_pct: 33.33 }),
            slice('C', 100, { weight_pct: 33.33 }),
        ],
    });
    const covered = donutSegments(g).reduce((sum, s) => sum + s.dash, 0);
    assert.ok(Math.abs(covered - 100) < 1e-9);
});

test('a 40-60 name book keeps its head and folds its tail, naming the count', () => {
    const many = Array.from({ length: 50 }, (_, i) =>
        slice(`S${String(i).padStart(2, '0')}`, 100 - i),
    );
    const g = groupAllocation({ slices: many });
    assert.equal(g.length, ALLOCATION_TOP_N + 1);
    const tail = g[g.length - 1];
    assert.equal(tail.isOthers, true);
    assert.equal(tail.symbols.length, 50 - ALLOCATION_TOP_N);
    assert.match(tail.label, /อื่นๆ \(42 รายการ\)/);
    // The tail is a real share of the ring, not a leftover: value and weight
    // both add up.
    const covered = donutSegments(g).reduce((sum, s) => sum + s.dash, 0);
    assert.ok(Math.abs(covered - 100) < 1e-9);
    assert.ok(Math.abs(g.reduce((s, x) => s + x.weight_pct, 0) - 100) < 1e-9);
});

test('exactly topN holdings are not folded into an "others" of one', () => {
    const exact = Array.from({ length: ALLOCATION_TOP_N }, (_, i) => slice(`S${i}`, 10 + i));
    const g = groupAllocation({ slices: exact });
    assert.equal(g.length, ALLOCATION_TOP_N);
    assert.equal(g.some((s) => s.isOthers), false);
});

test('an excluded position never becomes a zero-width wedge', () => {
    // The backend sends no slice for it at all; a defensive zero must also not
    // be drawn if one ever arrives.
    const g = groupAllocation({
        slices: [slice('PTT.BK', 40_000), slice('KBANK.BK', 0)],
        excluded: [{ symbol: 'KBANK.BK', reason: 'unpriced' }],
    });
    assert.deepEqual(g.map((s) => s.label), ['PTT.BK']);
    assert.equal(g[0].weight_pct, 100);
});

test('an all-excluded book draws no ring at all', () => {
    const a = {
        slices: [],
        total_value: 0,
        excluded: [
            { symbol: 'PTT.BK', reason: 'unpriced' },
            { symbol: 'KBANK.BK', reason: 'unpriced' },
        ],
    };
    assert.deepEqual(groupAllocation(a), []);
    assert.deepEqual(donutSegments(groupAllocation(a)), []);
    // ...but the panel still renders, because the exclusions are the message.
    assert.equal(hasAllocation(a), true);
});

test('nothing at all renders nothing', () => {
    assert.equal(hasAllocation(null), false);
    assert.equal(hasAllocation({ slices: [], excluded: [] }), false);
    assert.deepEqual(groupAllocation(null), []);
    assert.deepEqual(groupAllocation(undefined), []);
});

test('the exclusion sentence names every symbol, grouped by reason', () => {
    const s = exclusionSentence({
        excluded: [
            { symbol: 'KBANK.BK', reason: 'unpriced' },
            { symbol: 'NVDA', reason: 'currency_conflict' },
            { symbol: 'PTT.BK', reason: 'unpriced' },
        ],
    });
    assert.ok(s);
    assert.match(s!, /KBANK\.BK, PTT\.BK \(ยังไม่มีราคาล่าสุด\)/);
    assert.match(s!, /NVDA \(สกุลเงินไม่ตรงกัน\)/);
    // The reading the user must never have to guess.
    assert.match(s!, /ไม่ได้แปลว่ามูลค่าเป็น 0/);
});

test('every backend reason has Thai wording, and an unknown one is not swallowed', () => {
    for (const reason of ['unpriced', 'fx_unavailable', 'currency_conflict', 'unstatable']) {
        const s = exclusionSentence({ excluded: [{ symbol: 'X', reason }] });
        assert.ok(s && !s.includes(reason), `reason "${reason}" rendered untranslated`);
    }
    const unknown = exclusionSentence({ excluded: [{ symbol: 'X', reason: 'brand_new' }] });
    assert.match(unknown!, /brand_new/);
});

test('a fully statable book says nothing extra', () => {
    assert.equal(exclusionSentence({ slices: [slice('A', 1)], excluded: [] }), null);
    assert.equal(exclusionSentence(null), null);
});

test('slice colours are deterministic and distinct across the head', () => {
    const colors = new Set(Array.from({ length: ALLOCATION_TOP_N }, (_, i) => sliceColor(i)));
    assert.equal(colors.size, ALLOCATION_TOP_N);
    assert.equal(sliceColor(3), sliceColor(3));
});
