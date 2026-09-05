// bd:shotockviz-43x — `expired` mapping removed: the backend's
// `AlertStatus.EXPIRED` was declared but never assigned by any code path
// (models/alert.py), so this frontend key was displayable but
// unreachable outside a manual DB seed. Struck per Oliver/Tara's call
// ("resolve by striking, not by implementing" — 10-tara-value.md) rather
// than building an expiry rule nobody asked for. Only the two statuses
// the backend actually assigns are mapped here — see models/alert.py's
// AlertStatus for the removal note and the DB-enum finding.
//
// bd:shotockviz-o0b — `AlertStatus.INACTIVE` (the backend enum member,
// distinct from the `is_active` field below) had the same never-assigned
// defect and is now struck from the backend enum too. No change needed
// here: this function never read an INACTIVE *status* string off the
// wire in the first place — the 'inactive' key it returns has always
// come from `is_active: false`, which is correct and stays correct.
// `status` (lifecycle: has it fired?) and `is_active` (user pause
// control) are deliberately two fields, not one — see REQUIREMENTS.md
// FR-ALERT-003 for the full reasoning.

export type AlertStatusKey = 'active' | 'triggered' | 'inactive';

export interface AlertStatusInput {
    status?: string | null;
    is_active?: boolean;
}

export function getAlertStatusKey(alert: AlertStatusInput): AlertStatusKey {
    if (alert.status === 'TRIGGERED') return 'triggered';
    return alert.is_active ? 'active' : 'inactive';
}
