// bd:ui-honesty-2026-09 F11 — STATUS_STYLE (AlertsPage.tsx:17-21) had no
// `expired` key so an expired alert fell through to the `active`/`inactive`
// mapping and showed "หยุดชั่วคราว" (paused). Per Oliver handoff
// (05-oliver-phase2-handoff.md): backend alert status enum has EXPIRED
// (uppercase, same convention as the existing 'TRIGGERED' check at
// AlertsPage.tsx:205) — this is a pure frontend mapping gap, SMALL-FIX.

export type AlertStatusKey = 'active' | 'triggered' | 'inactive' | 'expired';

export interface AlertStatusInput {
    status?: string | null;
    is_active?: boolean;
}

export function getAlertStatusKey(alert: AlertStatusInput): AlertStatusKey {
    if (alert.status === 'EXPIRED') return 'expired';
    if (alert.status === 'TRIGGERED') return 'triggered';
    return alert.is_active ? 'active' : 'inactive';
}
