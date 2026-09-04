/**
 * Pure S/R price-line color + label helpers — bd:features-2026-09 slice 2.
 *
 * Split out as a standalone, dependency-free module (no `@/store/*` path
 * aliases) so it's importable by the plain Node test runner with zero build
 * step, following the same pattern as ./hooks/wsDataReady.ts.
 *
 * Color rule (user-confirmed, do not deviate):
 *  - Use the row's `color` column when present (already populated for most
 *    imported rows: support='#fde047' yellow, resistance='#a78bfa' purple).
 *  - When `color` is NULL, fall back to a fixed color by level_type:
 *    support = yellow, resistance = magenta. Exact fallback hexes are a Dave
 *    judgment call (user said "your call") — chosen for readability against
 *    both the dark (#0d0f17) and light (#f8f9fc) chart backgrounds
 *    (see TradingChart.tsx bgColor).
 */

export type SrLevelType = 'support' | 'resistance';

export interface SrLevelLike {
    color?: string | null;
    level_type?: SrLevelType | string;
    tag?: string | null;
}

/** Fallback hexes used only when a row's `color` column is NULL. */
export const SR_LEVEL_FALLBACK_COLOR: Record<SrLevelType, string> = {
    support: '#eab308',    // amber-500 "yellow" — readable on light + dark bg
    resistance: '#d946ef', // fuchsia-500 "magenta" — readable on light + dark bg
};

const DEFAULT_FALLBACK = '#9ca3af'; // neutral gray — only hit if level_type is somehow neither

/**
 * Resolve the color to paint a single S/R price line with:
 * row color when present, else the fixed by-type fallback.
 */
export function resolveSrLevelColor(level: SrLevelLike): string {
    if (level.color) return level.color;
    if (level.level_type === 'support' || level.level_type === 'resistance') {
        return SR_LEVEL_FALLBACK_COLOR[level.level_type];
    }
    return DEFAULT_FALLBACK;
}

/** Price-line label: the row's `tag` if present, else no label. */
export function resolveSrLevelTitle(level: SrLevelLike): string {
    return level.tag || '';
}
