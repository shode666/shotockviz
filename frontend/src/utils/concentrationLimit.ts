// bd:shotockviz-649 — "concentration as a limit, not just a display".
//
// bd:shotockviz-916 shipped the % breakdown (`utils/allocation.ts`) so he can
// SEE that one name is 74% of the book; this is the follow-on that TELLS him,
// instead of asking him to re-read a donut every session.
//
// The breach math itself is NOT duplicated here. It lives exactly once, in
// `services/portfolio_service.py::build_concentration_check`, which already
// inherits `build_allocation`'s three exclusions (rule 2 unpriced, rule 4
// fx_unavailable, rule 5 currency_conflict) so a position with no stated %
// cannot be read as either "under the limit" or "over" it — see that
// module's "RULE 1 / RULE 5 COLLISION" note. This file consumes that result
// (`GET /portfolio/analytics?concentration_limit_pct=`, the `concentration`
// field) and is responsible for exactly two things a backend response cannot
// do for itself:
//
//   1. WHERE THE LIMIT LIVES. Not a new column on `users` (this bead's
//      backend file scope has no migration and does not touch
//      `models/user.py`) — `limit_pct` is a per-request parameter, and this
//      is the ONE place it is remembered: localStorage, keyed by user id, so
//      "he sets it once" is true on this device across sessions. It is NOT
//      synced across devices/browsers — that is the honest boundary of this
//      iteration, and whether it should become a real per-user server
//      setting (its own migration, its own bead, alongside
//      `users.telegram_chat_id`) is an open question for Oliver.
//
//   2. Turning the backend's `not_checked` list into the same sentence
//      `utils/allocation.ts` already builds for `Allocation.excluded` —
//      reusing `reasonText` from there rather than a second reason map, so
//      the two screens cannot describe the same exclusion differently.
//
// `MIN_/MAX_/DEFAULT_CONCENTRATION_LIMIT_PCT` restate the three constants
// pinned in `services/portfolio_service.py` (same names, same values) so the
// input widget can validate before round-tripping to the server. A language
// boundary means they cannot be the literal same object; if the backend ever
// changes them, this file has to change too — same risk class as any
// constant duplicated across a client/server boundary, and worth a shared
// test fixture if the values ever drift in practice.

import { reasonText } from './allocation.ts';

export const MIN_CONCENTRATION_LIMIT_PCT = 1;
export const MAX_CONCENTRATION_LIMIT_PCT = 99;
export const DEFAULT_CONCENTRATION_LIMIT_PCT = 25;

export function isValidConcentrationLimitPct(value: number): boolean {
    return (
        Number.isFinite(value) &&
        value >= MIN_CONCENTRATION_LIMIT_PCT &&
        value <= MAX_CONCENTRATION_LIMIT_PCT
    );
}

// ─── Persistence (client-side "where the limit lives") ─────────────────────
// SSR-safe: TanStack Start renders on the server, where `window` does not
// exist — same guard convention as `store/appStore.ts` / `store/authStore.ts`.
const isBrowser = typeof window !== 'undefined';

/** One key per user: a shared browser must not show user A's threshold to B. */
export function concentrationLimitStorageKey(userId: number | string): string {
    return `shotockviz.concentration_limit_pct.${userId}`;
}

/**
 * The trader's remembered threshold, or the default when none is set yet /
 * storage is unavailable / the stored value is no longer valid (the bounds
 * could have changed under an old value). Never throws.
 */
export function loadConcentrationLimitPct(
    userId: number | string | null | undefined,
): number {
    if (!isBrowser || userId == null) return DEFAULT_CONCENTRATION_LIMIT_PCT;
    let raw: string | null = null;
    try {
        raw = window.localStorage.getItem(concentrationLimitStorageKey(userId));
    } catch {
        return DEFAULT_CONCENTRATION_LIMIT_PCT; // storage disabled/blocked — degrade, don't throw
    }
    if (raw == null) return DEFAULT_CONCENTRATION_LIMIT_PCT;
    const parsed = Number(raw);
    return isValidConcentrationLimitPct(parsed) ? parsed : DEFAULT_CONCENTRATION_LIMIT_PCT;
}

/** No-op (not a throw) on an invalid value or an unavailable store — the
 * input's own validation message is the place that tells the user why their
 * value didn't take; silently keeping the last-good value here is correct. */
export function saveConcentrationLimitPct(
    userId: number | string | null | undefined,
    pct: number,
): void {
    if (!isBrowser || userId == null || !isValidConcentrationLimitPct(pct)) return;
    try {
        window.localStorage.setItem(concentrationLimitStorageKey(userId), String(pct));
    } catch {
        // storage disabled/blocked/quota-full — the trader still sees the
        // check this session; it just will not survive a reload.
    }
}

// ─── Display: the backend payload -> what must be said about it ────────────

export interface ConcentrationBreachInput {
    symbol: string;
    currency?: string;
    weight_pct: number;
    limit_pct: number;
    excess_pct: number;
    value_base: number;
    trim_value_base: number;
}

export interface ConcentrationNotCheckedInput {
    symbol: string;
    /** unpriced | fx_unavailable | currency_conflict | unstatable — same
     * vocabulary as `Allocation.excluded`, because it IS that list. */
    reason: string;
}

export interface ConcentrationInput {
    limit_pct?: number;
    base_currency?: string;
    breaches?: ConcentrationBreachInput[] | null;
    not_checked?: ConcentrationNotCheckedInput[] | null;
}

/** True when there is at least one name over the limit right now. A breach
 * that is only ever true is noise — this is deliberately a point-in-time
 * read, not a sticky flag, so it goes false again the moment the book does. */
export function hasConcentrationBreach(c: ConcentrationInput | null | undefined): boolean {
    return (c?.breaches?.length ?? 0) > 0;
}

/**
 * The sentence that must be rendered WITH the breach list whenever the check
 * could not see the whole book — the same doctrine as
 * `utils/allocation.ts::exclusionSentence`, extended one level: a position
 * with no allocation % cannot be said to have crossed a limit either, so it
 * is named here as "not checked", never silently read as compliant.
 *
 * Null when every position was checkable (nothing to disclose).
 */
export function notCheckedSentence(c: ConcentrationInput | null | undefined): string | null {
    const notChecked = c?.not_checked ?? [];
    if (notChecked.length === 0) return null;

    const byReason = new Map<string, string[]>();
    for (const e of notChecked) {
        const bucket = byReason.get(e.reason) ?? [];
        bucket.push(e.symbol);
        byReason.set(e.reason, bucket);
    }
    const parts = [...byReason.entries()].map(
        ([reason, symbols]) => `${symbols.join(', ')} (${reasonText(reason)})`,
    );
    return (
        `ยังตรวจสอบไม่ได้: ${parts.join(' · ')} ` +
        `— ไม่ทราบสัดส่วน จึงบอกไม่ได้ว่าเกินขีดจำกัดหรือไม่ (ไม่ได้แปลว่าอยู่ในเกณฑ์ปลอดภัย)`
    );
}
