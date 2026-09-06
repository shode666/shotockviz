// bd:shotockviz-916 / FR-PORT-002 — the allocation breakdown, as pure functions.
//
// The chart itself is inline SVG (see PortfolioPage.tsx). There is no charting
// dependency for this: `lightweight-charts` (package.json:25) draws time series,
// not shares of a whole, and the no-new-deps NFR (ADR-UH-003,
// docs/engagements/ui-honesty-2026-09.md) rules out adding one for a single
// donut. Everything that could be got wrong — grouping, geometry, and the
// sentence naming what is NOT in the picture — lives here so it can be tested
// under `node --test` without a renderer.
//
// The rule inherited from the backend (services/portfolio_service.py,
// `build_allocation`): a position whose value is unknown gets NO SLICE and is
// NAMED. An unpriced Thai position after 16:30 ICT is not a 0% wedge — a 0%
// wedge says "this name is worth nothing", which is the claim bd:shotockviz-2w8
// exists to stop the product making.
//
// Two things this module refuses to do:
//   * invent an area for an excluded position (it has none — that is the point);
//   * label the ring with weights that do not describe the ring. Every weight
//     below is recomputed from the values actually drawn, so what the legend
//     says and what the arcs cover are the same numbers.

export interface AllocationSliceInput {
    symbol: string;
    currency?: string;
    /** Base-currency market value. THE area. */
    value_base: number;
    /** Backend's weight against the header total; recomputed here for labels. */
    weight_pct?: number;
    split_adjusted?: boolean;
    rights_unstatable?: boolean;
}

export interface AllocationExclusionInput {
    symbol: string;
    /** unpriced | fx_unavailable | currency_conflict | unstatable */
    reason: string;
}

export interface AllocationInput {
    basis?: string;
    base_currency?: string;
    /** The denominator — the same number the header prints. */
    total_value?: number;
    slices?: AllocationSliceInput[] | null;
    excluded?: AllocationExclusionInput[] | null;
    fx_estimated?: boolean;
}

/**
 * How many names get their own slice before the tail is grouped.
 *
 * The book this is built for runs 40-60 symbols (CLAUDE.md, stakeholder
 * context). Fifty wedges is not a picture of anything, and the concentration
 * question — "how much is in one name?" — is answered by the head of the
 * distribution. The tail is not hidden: it becomes one slice that says how many
 * names it contains and what they add up to.
 */
export const ALLOCATION_TOP_N = 8;

export interface DisplaySlice {
    key: string;
    label: string;
    /** Every symbol folded into this slice (1, or many for the tail). */
    symbols: string[];
    value_base: number;
    /** Share of the DRAWN ring, so the legend and the arcs cannot disagree. */
    weight_pct: number;
    isOthers: boolean;
    color: string;
    /** At least one symbol here is split-restated or rights-unstatable. */
    qualified: boolean;
}

// Deterministic, evenly-spread hues (golden angle). The colours carry no
// meaning — they only have to be told apart — so they are generated rather
// than themed, and the tail is deliberately neutral grey so it does not read as
// just another holding.
const OTHERS_COLOR = 'hsl(220 9% 46%)';
export function sliceColor(index: number): string {
    return `hsl(${(index * 137.508) % 360} 58% 55%)`;
}

const othersLabel = (n: number) => `อื่นๆ (${n} รายการ)`;

/**
 * Head of the distribution as individual slices, tail folded into one.
 *
 * Returns [] when there is nothing statable — a book whose every position is
 * excluded draws no ring at all, because a percentage of nothing is undefined,
 * not zero.
 */
export function groupAllocation(
    a: AllocationInput | null | undefined,
    topN: number = ALLOCATION_TOP_N,
): DisplaySlice[] {
    const slices = (a?.slices ?? []).filter((s) => s && s.value_base > 0);
    if (slices.length === 0) return [];

    // Sorted here as well as on the server: this function must not depend on a
    // payload's order to put the biggest position first.
    const sorted = [...slices].sort((x, y) => y.value_base - x.value_base || x.symbol.localeCompare(y.symbol));
    const drawnTotal = sorted.reduce((sum, s) => sum + s.value_base, 0);
    if (drawnTotal <= 0) return [];

    const head = sorted.length > topN ? sorted.slice(0, topN) : sorted;
    const tail = sorted.length > topN ? sorted.slice(topN) : [];

    const out: DisplaySlice[] = head.map((s, i) => ({
        key: s.symbol,
        label: s.symbol,
        symbols: [s.symbol],
        value_base: s.value_base,
        weight_pct: (s.value_base / drawnTotal) * 100,
        isOthers: false,
        color: sliceColor(i),
        qualified: Boolean(s.split_adjusted || s.rights_unstatable),
    }));

    if (tail.length > 0) {
        const value = tail.reduce((sum, s) => sum + s.value_base, 0);
        out.push({
            key: '__others__',
            label: othersLabel(tail.length),
            symbols: tail.map((s) => s.symbol),
            value_base: value,
            weight_pct: (value / drawnTotal) * 100,
            isOthers: true,
            color: OTHERS_COLOR,
            qualified: tail.some((s) => s.split_adjusted || s.rights_unstatable),
        });
    }
    return out;
}

export interface DonutSegment {
    key: string;
    /** Arc length, in the same units as `gap`/`offset`. */
    dash: number;
    gap: number;
    /** SVG stroke-dashoffset (negative = clockwise from the start). */
    offset: number;
}

/**
 * Ring geometry in a 0-100 space — the caller sets `pathLength={100}` on the
 * circle, so no radius arithmetic is involved and the ring closes exactly.
 *
 * Fractions come from `value_base`, never from a rounded percentage, which is
 * why the arcs always cover the full circle.
 */
export function donutSegments(slices: DisplaySlice[]): DonutSegment[] {
    const total = slices.reduce((sum, s) => sum + s.value_base, 0);
    if (total <= 0) return [];
    let cumulative = 0;
    return slices.map((s) => {
        const dash = (s.value_base / total) * 100;
        // `cumulative === 0 ? 0 : -cumulative` — plain 0, never -0, so the value
        // compares and serialises the way a reader expects.
        const seg: DonutSegment = {
            key: s.key,
            dash,
            gap: 100 - dash,
            offset: cumulative === 0 ? 0 : -cumulative,
        };
        cumulative += dash;
        return seg;
    });
}

// Why a position has no slice, in the user's words. Same three reasons the
// backend names, plus the unreachable-by-construction fourth.
const REASON_TH: Record<string, string> = {
    unpriced: 'ยังไม่มีราคาล่าสุด',
    fx_unavailable: 'ไม่มีอัตราแลกเปลี่ยน',
    currency_conflict: 'สกุลเงินไม่ตรงกัน',
    unstatable: 'ระบุมูลค่าไม่ได้',
};

export const reasonText = (reason: string): string => REASON_TH[reason] ?? reason;

/**
 * The sentence that must be rendered WITH the chart whenever anything was left
 * out of it. Null when the picture is the whole statable book.
 *
 * It names every excluded symbol and its reason, and says the reading the user
 * must not have to guess at: excluded is not zero.
 */
export function exclusionSentence(a: AllocationInput | null | undefined): string | null {
    const excluded = a?.excluded ?? [];
    if (excluded.length === 0) return null;

    const byReason = new Map<string, string[]>();
    for (const e of excluded) {
        const bucket = byReason.get(e.reason) ?? [];
        bucket.push(e.symbol);
        byReason.set(e.reason, bucket);
    }
    const parts = [...byReason.entries()].map(
        ([reason, symbols]) => `${symbols.join(', ')} (${reasonText(reason)})`,
    );
    return (
        `สัดส่วนนี้ไม่รวม ${parts.join(' · ')} ` +
        `— ไม่ทราบมูลค่า จึงไม่มีสัดส่วนให้แสดง (ไม่ได้แปลว่ามูลค่าเป็น 0)`
    );
}

/**
 * True when there is a ring to draw. A book with slices but no exclusions, or
 * with both, renders; a book with neither renders nothing rather than an empty
 * panel with a heading.
 */
export function hasAllocation(a: AllocationInput | null | undefined): boolean {
    return groupAllocation(a).length > 0 || (a?.excluded ?? []).length > 0;
}
