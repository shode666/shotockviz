/**
 * Unit tests — syncSrPriceLines lifecycle (bd:features-2026-09 slice 2
 * iter3, Chris Finding 3, 02-chris-review.md: "zero regression test for the
 * exact lifecycle Finding 2 verifies by hand-reading... a component test
 * (mock lightweight-charts createChart/createPriceLine/removePriceLine),
 * assert removePriceLine is called with the pre-flip line objects and
 * createPriceLine is called fresh post-flip on symbol change + on a
 * darkMode-driven recreation").
 *
 * Run: `cd frontend && npm test` (== `node --test`), same runner convention
 * as src/hooks/useWebSocket.test.ts and src/utils/srLevelColor.test.ts.
 *
 * A fake `series` object (plain object with call-recording arrays) stands
 * in for lightweight-charts' ISeriesApi — no jsdom/React render needed,
 * since the lifecycle logic itself was split into a pure function
 * (syncSrPriceLines.ts) precisely so it's testable this way.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { LineStyle } from 'lightweight-charts';
import { syncSrPriceLines, type SrLineSeriesLike } from './syncSrPriceLines.ts';

interface FakeLine {
    __id: number;
    options: { price: number; color: string; title: string; lineStyle: LineStyle };
}

function makeFakeSeries() {
    const created: FakeLine[] = [];
    const removed: unknown[] = [];
    let nextId = 0;

    const series: SrLineSeriesLike = {
        createPriceLine(options) {
            const line: FakeLine = { __id: nextId++, options };
            created.push(line);
            return line;
        },
        removePriceLine(line) {
            removed.push(line);
        },
    };

    return { series, created, removed };
}

const LEVELS = [
    { price: 100, level_type: 'support' as const, tag: 'S1', color: '#fde047' },
    { price: 200, level_type: 'resistance' as const, tag: 'R1', color: null },
];

test('no series yet → no-op, prevLines returned unchanged', () => {
    const prevLines = [{ fake: 'line' }];
    const result = syncSrPriceLines(null, prevLines, LEVELS, true);
    assert.equal(result, prevLines);
});

test('showSrLevels=false with no prior lines → nothing created, nothing removed', () => {
    const { series, created, removed } = makeFakeSeries();
    const result = syncSrPriceLines(series, [], LEVELS, false);
    assert.deepEqual(result, []);
    assert.equal(created.length, 0);
    assert.equal(removed.length, 0);
});

test('showSrLevels=true draws one createPriceLine per level, returns the new line objects', () => {
    const { series, created } = makeFakeSeries();
    const result = syncSrPriceLines(series, [], LEVELS, true);
    assert.equal(created.length, 2);
    assert.equal(result.length, 2);
    assert.deepEqual(result, created);
    assert.equal(created[0].options.title, 'S1');
    assert.equal(created[1].options.title, 'R1');
});

// ── Symbol change: clear old lines, draw new ones ───────────────────────────

test('symbol change: old lines are removed via removePriceLine, new levels are drawn fresh', () => {
    const { series, created, removed } = makeFakeSeries();

    // Initial draw for symbol A
    const linesForA = syncSrPriceLines(series, [], LEVELS, true);
    assert.equal(created.length, 2);

    // Symbol changes to B — useSrLevels() would return a new levels array;
    // the effect re-runs with the PREVIOUS lines (linesForA) as prevLines.
    const levelsForB = [{ price: 50, level_type: 'support' as const, tag: 'S9', color: null }];
    const linesForB = syncSrPriceLines(series, linesForA, levelsForB, true);

    // The 2 old (symbol A) line objects were removed — exactly those, not
    // some other set.
    assert.equal(removed.length, 2);
    assert.deepEqual(removed, linesForA);

    // A fresh line was created for symbol B's level — not reused from A.
    assert.equal(created.length, 3); // 2 from A + 1 from B
    assert.equal(linesForB.length, 1);
    assert.equal((linesForB[0] as FakeLine).options.title, 'S9');
    assert.ok(!linesForA.includes(linesForB[0]), 'symbol B line must be a new object, not an A line reused');
});

// ── Toggle off then on: lines cleared, then redrawn from current levels ────

test('toggle off clears all lines; toggling back on redraws from the current level list', () => {
    const { series, removed } = makeFakeSeries();

    const drawn = syncSrPriceLines(series, [], LEVELS, true);
    assert.equal(drawn.length, 2);

    const afterToggleOff = syncSrPriceLines(series, drawn, LEVELS, false);
    assert.deepEqual(afterToggleOff, []);
    assert.deepEqual(removed, drawn); // the exact objects that were on-screen got removed

    const afterToggleOn = syncSrPriceLines(series, afterToggleOff, LEVELS, true);
    assert.equal(afterToggleOn.length, 2);
});

// ── Chart recreation (chartGeneration bump): stale lines from the disposed
// series must not be double-cleared or orphaned on the new series ─────────

test('chart recreation: prevLines from a disposed series are passed to removePriceLine on the NEW series and swallowed (try/catch), new lines are drawn clean on the new series', () => {
    const { series: oldSeries } = makeFakeSeries();
    const linesOnOldSeries = syncSrPriceLines(oldSeries, [], LEVELS, true);
    assert.equal(linesOnOldSeries.length, 2);

    // Chart recreated (e.g. darkMode flip) — a brand NEW series object.
    // TradingChart.tsx's srPriceLinesRef still holds `linesOnOldSeries`
    // (the disposed series' line objects) at the moment this effect re-runs,
    // per Chris Finding 2's traced ordering.
    const newSeries: SrLineSeriesLike = {
        createPriceLine(options) {
            return { __id: 'new', options };
        },
        removePriceLine() {
            // A real disposed-chart series throws here; this fake reproduces
            // that so the try/catch in syncSrPriceLines is actually exercised.
            throw new Error('cannot remove price line: series is disposed');
        },
    };

    let thrown = false;
    try {
        const result = syncSrPriceLines(newSeries, linesOnOldSeries, LEVELS, true);
        // Must not propagate the throw, and must still draw fresh lines on
        // the new series (not silently give up after the removal failure).
        assert.equal(result.length, 2);
        assert.ok(result.every((l: any) => l.__id === 'new'), 'new lines must belong to the new series, not carry over stale objects');
    } catch {
        thrown = true;
    }
    assert.equal(thrown, false, 'a disposed-series removePriceLine throw must be swallowed, not propagated');
});

test('chart recreation with showSrLevels currently false: old lines are still cleaned up (attempted), nothing new is drawn', () => {
    const { series: oldSeries } = makeFakeSeries();
    const linesOnOldSeries = syncSrPriceLines(oldSeries, [], LEVELS, true);

    let removeCalls = 0;
    const newSeries: SrLineSeriesLike = {
        createPriceLine() { throw new Error('must not be called'); },
        removePriceLine() { removeCalls++; },
    };

    const result = syncSrPriceLines(newSeries, linesOnOldSeries, LEVELS, false);
    assert.equal(removeCalls, 2, 'cleanup must still be attempted for every stale line even when toggled off');
    assert.deepEqual(result, []);
});

// ── lineStyle per source (bd:features-2026-09 slice A) ──────────────────────
// dashed = computed (auto_pivot), solid = user-owned (manual_import /
// user_created). This is a deliberate FLIP for manual_import rows, which
// previously rendered dashed too (everything was hardcoded Dashed).

test('auto_pivot level renders Dashed', () => {
    const { series, created } = makeFakeSeries();
    const levels = [{ price: 100, level_type: 'support' as const, tag: 'AUTO S1', color: null, source: 'auto_pivot' }];
    syncSrPriceLines(series, [], levels, true);
    assert.equal((created[0] as FakeLine).options.lineStyle, LineStyle.Dashed);
});

test('manual_import level renders Solid (flip from the old hardcoded Dashed)', () => {
    const { series, created } = makeFakeSeries();
    const levels = [{ price: 100, level_type: 'support' as const, tag: 'S1', color: '#fde047', source: 'manual_import' }];
    syncSrPriceLines(series, [], levels, true);
    assert.equal((created[0] as FakeLine).options.lineStyle, LineStyle.Solid);
});

test('user_created level renders Solid', () => {
    const { series, created } = makeFakeSeries();
    const levels = [{ price: 100, level_type: 'support' as const, tag: 'S1', color: null, source: 'user_created' }];
    syncSrPriceLines(series, [], levels, true);
    assert.equal((created[0] as FakeLine).options.lineStyle, LineStyle.Solid);
});

test('missing/undefined source renders Solid (defaults to "user-owned" style, not computed)', () => {
    const { series, created } = makeFakeSeries();
    const levels = [{ price: 100, level_type: 'support' as const, tag: 'S1', color: null }];
    syncSrPriceLines(series, [], levels, true);
    assert.equal((created[0] as FakeLine).options.lineStyle, LineStyle.Solid);
});
