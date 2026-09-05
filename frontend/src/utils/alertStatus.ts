// bd:shotockviz-43x — `expired` mapping removed: the backend's
// `AlertStatus.EXPIRED` was declared but never assigned by any code path
// (models/alert.py), so this frontend key was displayable but
// unreachable outside a manual DB seed. Struck per Oliver/Tara's call
// ("resolve by striking, not by implementing" — 10-tara-value.md) rather
// than building an expiry rule nobody asked for. Only the two statuses
// the backend actually assigns are mapped here — see models/alert.py's
// AlertStatus for the removal note and the DB-enum finding.

export type AlertStatusKey = 'active' | 'triggered' | 'inactive';

export interface AlertStatusInput {
    status?: string | null;
    is_active?: boolean;
}

export function getAlertStatusKey(alert: AlertStatusInput): AlertStatusKey {
    if (alert.status === 'TRIGGERED') return 'triggered';
    return alert.is_active ? 'active' : 'inactive';
}
