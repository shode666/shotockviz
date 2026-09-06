/**
 * Pure "how old is this cached number" formatter.
 *
 * bd:shotockviz-f14 — "no cached number says how old it is". Extends the
 * treatment `utils/statusBar.ts` already gives the price field
 * (bd:shotockviz-09j) to numbers with a HOURS-scale refresh cadence
 * (fundamentals: 4h, `workers/fundamentals_fetcher.py`), where a
 * minutes-tuned amber/red traffic light doesn't apply and hasn't been
 * asked for. This module deliberately does NOT invent fresh/stale tone
 * thresholds for a cadence nobody has spec'd — it states the real age, or
 * says explicitly that the age is unknown. Do not synthesize a number when
 * the true as-of time isn't known (same rule statusBar.ts follows).
 */

export interface CachedValueAge {
    /** Whether a real server-stamped timestamp was available to derive this from. */
    known: boolean;
    label: string;
}

/**
 * @param tsSeconds - server epoch SECONDS the cached value was fetched, or
 *   `null`/`undefined` if unknown.
 * @param nowMs - caller-supplied wall-clock ms (injected, not read
 *   internally, so this stays pure and testable — the caller re-renders on
 *   an interval to advance it, same pattern as statusBar.ts).
 */
export function formatCachedAge(tsSeconds: number | null | undefined, nowMs: number): CachedValueAge {
    if (tsSeconds == null) {
        return { known: false, label: 'ไม่ทราบเวลาข้อมูล' };
    }

    const ageMs = Math.max(0, nowMs - tsSeconds * 1000);
    const totalMins = Math.floor(ageMs / 60_000);

    if (totalMins < 1) {
        return { known: true, label: 'เมื่อครู่นี้' };
    }

    if (totalMins < 60) {
        return { known: true, label: `${totalMins} นาทีที่แล้ว` };
    }

    const hours = Math.floor(totalMins / 60);
    const mins = totalMins % 60;
    const label = mins > 0 ? `${hours} ชม. ${mins} นาทีที่แล้ว` : `${hours} ชม.ที่แล้ว`;
    return { known: true, label };
}
