/**
 * Market status utilities — purely client-side, no API calls needed.
 * Uses local system clock converted to the relevant timezone.
 */

export interface MarketStatusResult {
    open: boolean;
    label: string;
    color: 'green' | 'yellow' | 'gray';
    pulse: boolean;
}

/** SET (Stock Exchange of Thailand) — Bangkok UTC+7
 *  Sessions: Morning 10:00–12:30, Afternoon 14:30–16:30 (local time)
 *  Pre-open: 09:30–10:00 (yellow, pulse)
 */
export function getSetStatus(): MarketStatusResult {
    const now = new Date();
    // Bangkok = UTC + 7h
    const bkk = new Date(now.getTime() + 7 * 3_600_000);
    const day = bkk.getUTCDay(); // 0 = Sunday, 6 = Saturday
    const mins = bkk.getUTCHours() * 60 + bkk.getUTCMinutes();

    if (day === 0 || day === 6) {
        return { open: false, label: 'SET Closed', color: 'gray', pulse: false };
    }

    // Pre-open: 09:30–10:00 (570–600)
    if (mins >= 570 && mins < 600) {
        return { open: false, label: 'SET Pre-open', color: 'yellow', pulse: true };
    }
    // Morning session: 10:00–12:30 (600–750)
    if (mins >= 600 && mins < 750) {
        return { open: true, label: 'SET Open', color: 'green', pulse: true };
    }
    // Lunch break: 12:30–14:30 (750–870)
    if (mins >= 750 && mins < 870) {
        return { open: false, label: 'SET Break', color: 'gray', pulse: false };
    }
    // Afternoon session: 14:30–16:30 (870–990)
    if (mins >= 870 && mins < 990) {
        return { open: true, label: 'SET Open', color: 'green', pulse: true };
    }

    return { open: false, label: 'SET Closed', color: 'gray', pulse: false };
}

/** US Stock Markets (NYSE/NASDAQ) — Eastern Time UTC-5 (EST) / UTC-4 (EDT)
 *  Regular hours: 09:30–16:00 ET
 *  Note: uses simplified UTC-5 (no DST detection)
 */
export function getUsStatus(): MarketStatusResult {
    const now = new Date();
    // Eastern Time ≈ UTC-5 (EST) — simplified, no DST
    const et = new Date(now.getTime() - 5 * 3_600_000);
    const day = et.getUTCDay();
    const mins = et.getUTCHours() * 60 + et.getUTCMinutes();

    if (day === 0 || day === 6) {
        return { open: false, label: 'US Closed', color: 'gray', pulse: false };
    }

    // Pre-market: 04:00–09:30 (240–570)
    if (mins >= 240 && mins < 570) {
        return { open: false, label: 'US Pre-mkt', color: 'yellow', pulse: false };
    }
    // Regular: 09:30–16:00 (570–960)
    if (mins >= 570 && mins < 960) {
        return { open: true, label: 'US Open', color: 'green', pulse: true };
    }
    // After-hours: 16:00–20:00 (960–1200)
    if (mins >= 960 && mins < 1200) {
        return { open: false, label: 'US After-hrs', color: 'yellow', pulse: false };
    }

    return { open: false, label: 'US Closed', color: 'gray', pulse: false };
}
