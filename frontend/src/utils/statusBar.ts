/**
 * Pure decision logic for StatusBar's "last update" label.
 *
 * bd:shotockviz-09j — REPLACES the data_ready-derived path from
 * ADR-UH-001/001a (`docs/engagements/ui-honesty-2026-09.md`). That path
 * (`formatLastUpdate`/`getLastQuoteTimestamp`/`nextLastUpdate`, removed
 * here) read "—" under healthy operation because `data_ready` with
 * `data_type:"quote"` only fires from the Celery-outage fallback
 * (`services/cache_orchestrator.py:340`) — Tara: a field that always reads
 * "—" trains the user to stop looking at it. The real 1-minute quote
 * refresh stamps a server `ts` into every quote payload
 * (`workers/helpers/cache_publisher.py:36`, forwarded verbatim by
 * `api/routes/stocks/quotes.py`); that `ts` is what this module derives
 * age from. `appStore.dataReadyPayload`/`setDataReadyPayload` are untouched
 * — `useChartData.ts` still consumes them for its own re-fetch logic.
 */

export type PriceFreshnessTone = 'fresh' | 'stale' | 'very-stale' | 'market-closed' | 'unknown';

export interface PriceFreshness {
    tone: PriceFreshnessTone;
    label: string;
}

// ── Thresholds ──────────────────────────────────────────────────────────
//
// Bella/Tara's spec proposed amber >2min / red >5min as a starting point.
// Verified against the actual fetch cadence before picking final numbers
// (NO MAGIC — don't ship someone else's guess unchecked):
//   - `price_fetcher.fetch_prices` round-robins ONE market slot per 60s
//     beat (`workers/celery_app.py` — `schedule: 60.0`) across
//     `MARKET_SLOTS` = 6 entries (SET/US/Asia/Europe/Crypto/Overview,
//     `workers/price_fetcher.py:117-128`). A given open market's own
//     symbols are therefore refetched roughly every one full cycle of that
//     round-robin — worst case 6 slots x 60s = 360s = 6 minutes if every
//     slot is open and gets its turn — before this fix's cache TTL of 120s
//     even factors in.
//   - So up to ~6 minutes of staleness during normal, fully-open-market
//     operation is expected, not a fault. Flagging RED at 5 minutes (before
//     one full cycle can even complete) would cry wolf on totally healthy
//     operation, which is the exact failure mode this bd exists to avoid.
// Picked: AMBER unchanged at 2 minutes (an early, non-alarming "this is
// aging" cue — the paragraph's "do not cry wolf" concern is about false
// alarms, i.e. RED, not a soft amber nudge). RED raised to 6 minutes
// (one full worst-case round-robin cycle) instead of the proposed 5 —
// beyond that, the fetch pipeline is actually stuck (e.g. Celery down),
// which is a real fault worth flagging.
// Open question for Bella: formalize this as the AC (bd:shotockviz-09j's
// own acceptance criteria calls for "an AC from Bella covering the
// thresholds" — this is Dave's evidenced default pending that sign-off).
const AMBER_MS = 2 * 60_000;
const RED_MS = 6 * 60_000;

/**
 * Thai "N minutes ago" / "just now" label for an age in milliseconds.
 * Rounds down to whole minutes — a price stamped 90s ago reads "1 นาทีที่แล้ว"
 * (matches "N minutes ago" being an approximation, not a stopwatch).
 */
export function formatAgeThai(ageMs: number): string {
    const mins = Math.floor(Math.max(0, ageMs) / 60_000);
    if (mins < 1) return 'เมื่อครู่นี้';
    return `${mins} นาทีที่แล้ว`;
}

/**
 * Decide the age/colour/label for the price currently shown, given:
 *   - `tsSeconds`: server epoch SECONDS the quote was cached (`PriceData.ts`),
 *     or `null`/`undefined` if no quote has ever loaded this session.
 *   - `nowMs`: caller-supplied wall-clock ms (injected, not read internally,
 *     so this function stays pure and testable — the caller re-renders on
 *     an interval to advance it).
 *   - `marketOpen`: whether the symbol's home market is open right now
 *     (`true`/`false` from `getSetStatus()`/`getUsStatus()`), or `null` when
 *     the symbol's market isn't one this codebase models client-side yet
 *     (FUND/CRYPTO/other) — in which case no market-closed override is
 *     applied, since claiming "closed" would itself be a guess.
 *
 * Market-closed handling: once staleness would otherwise read amber or red
 * AND the market is confirmed closed, show a "market closed" state instead
 * of either color — a stale price at 02:00 ICT on a SET symbol, or hours
 * into US after-hours, is not a fault (Oliver: "a stale price at 02:00 on a
 * SET symbol is not a fault"). This overrides amber too, not just red: once
 * the market is closed, ANY staleness up to the next session open is
 * expected, so amber would cry wolf exactly the same way red would — the
 * instruction's literal wording only named red, but the reasoning
 * ("do not cry wolf") applies equally to amber once the market has closed.
 * A genuinely fresh price (<= amber threshold) still displays as fresh even
 * if the market has since closed — no need to override something that
 * isn't alarming.
 */
export function getPriceFreshness(
    tsSeconds: number | null | undefined,
    nowMs: number,
    marketOpen: boolean | null,
): PriceFreshness {
    if (tsSeconds == null) {
        return { tone: 'unknown', label: '—' };
    }

    const ageMs = nowMs - tsSeconds * 1000;

    if (ageMs <= AMBER_MS) {
        return { tone: 'fresh', label: formatAgeThai(ageMs) };
    }

    if (marketOpen === false) {
        return { tone: 'market-closed', label: 'ตลาดปิด' };
    }

    if (ageMs > RED_MS) {
        return { tone: 'very-stale', label: formatAgeThai(ageMs) };
    }

    return { tone: 'stale', label: formatAgeThai(ageMs) };
}

/** Presentation mapping — kept alongside the decision function so every
 * consumer (today: StatusBar) uses the same colours for the same tones. */
export const PRICE_FRESHNESS_COLOR: Record<PriceFreshnessTone, string> = {
    fresh: 'var(--color-text-sub)',
    stale: '#f59e0b',            // amber-500 — matches Navbar's MarketBadge yellow
    'very-stale': 'var(--color-negative)', // rose-500 — matches AlertsPage's หมดอายุ
    'market-closed': 'var(--color-text-sub)',
    unknown: 'var(--color-text-sub)',
};
