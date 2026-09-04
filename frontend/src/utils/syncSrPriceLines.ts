/**
 * Pure S/R price-line lifecycle sync — bd:features-2026-09 slice 2 iter3
 * (Chris Finding 3, 02-chris-review.md — "zero regression test for the exact
 * lifecycle Finding 2 verifies by hand-reading").
 *
 * Split out of TradingChart.tsx's render effect into a standalone,
 * dependency-free function (no `@/store/*` aliases, no React) so the
 * create/cleanup lifecycle itself — not just the color-fallback pure
 * function — is exercisable by the plain Node test runner with a fake
 * `series` object, no jsdom/React-render step, no new dependency. Same
 * "split out for testability" pattern already established by
 * `./hooks/wsDataReady.ts` and `./utils/srLevelColor.ts`.
 *
 * `lightweight-charts` itself IS importable from plain `node --test`
 * (confirmed: `node --input-type=module -e "import * as lc from
 * 'lightweight-charts'"` resolves fine — it has proper ESM package
 * exports, unlike `@/store/*` path aliases which only Vite's bundler
 * resolves), so `LineStyle` is used for real here, not re-implemented.
 */
import { LineStyle } from 'lightweight-charts';
import { resolveSrLevelColor, resolveSrLevelTitle, type SrLevelLike } from './srLevelColor.ts';

/** The subset of lightweight-charts' `ISeriesApi` this module actually calls. */
export interface SrLineSeriesLike {
    createPriceLine(options: {
        price: number;
        color: string;
        lineWidth: number;
        lineStyle: LineStyle;
        axisLabelVisible: boolean;
        title: string;
    }): unknown;
    removePriceLine(line: unknown): void;
}

/**
 * Re-sync the S/R price lines drawn on `series` to match `levels` +
 * `showSrLevels`. Mirrors TradingChart.tsx's S/R effect body exactly:
 *
 *  1. No series yet (chart not created) → no-op, return `prevLines`
 *     unchanged (nothing to clear, nothing to draw).
 *  2. Always clear every line in `prevLines` first — `createPriceLine` has
 *     no "update" API, so toggling/refetching/recreating means
 *     remove-then-recreate. Each removal is wrapped so a `prevLines` entry
 *     that belongs to an already-disposed series (chart was just recreated
 *     — see TradingChart.tsx's `chartGeneration` comment) doesn't throw out
 *     of this function; it's a no-op in that case, which is correct: a
 *     disposed chart already discarded those objects.
 *  3. If `showSrLevels` is false → return `[]` (lines stay cleared, none
 *     redrawn).
 *  4. Otherwise, draw one `createPriceLine` per level and return the new
 *     line-object array (to become the next call's `prevLines`).
 */
export function syncSrPriceLines(
    series: SrLineSeriesLike | null | undefined,
    prevLines: unknown[],
    levels: SrLevelLike[],
    showSrLevels: boolean,
): unknown[] {
    if (!series) return prevLines;

    prevLines.forEach((line) => {
        try {
            series.removePriceLine(line);
        } catch {
            // Belonged to an already-disposed chart/series — nothing to clean up.
        }
    });

    if (!showSrLevels) return [];

    return levels.map((level) =>
        series.createPriceLine({
            price: (level as { price: number }).price,
            color: resolveSrLevelColor(level),
            lineWidth: 1,
            // bd:features-2026-09 slice A (09-sara-autopivot-crypto-spec.md
            // §3) — dashed = computed (auto_pivot), solid = user-owned
            // (manual_import/user_created). This is a visual convention
            // FLIP for pre-existing manual_import rows, which used to
            // render dashed too (everything was hardcoded Dashed before) —
            // see R2 visual-change note in the spec, release note required.
            lineStyle: level.source === 'auto_pivot' ? LineStyle.Dashed : LineStyle.Solid,
            axisLabelVisible: true,
            title: resolveSrLevelTitle(level),
        })
    );
}
