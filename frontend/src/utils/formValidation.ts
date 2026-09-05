// bd:ui-honesty-2026-09 F7 (ADR-UH-003) — pure validation functions, no library.
// Silent-return on empty required fields (AlertsPage.tsx:113-114,
// AddTransactionModal.tsx:118) replaced with inline errors driven by these.

export interface AlertFormFields {
    symbol: string;
    value: string;
}

export interface TransactionFormFields {
    symbol: string;
    qty: string;
    price: string;
}

export function validateAlertForm(fields: AlertFormFields): Record<string, string> {
    const errors: Record<string, string> = {};
    if (!fields.symbol || !fields.symbol.trim()) errors.symbol = 'กรุณาระบุ symbol';
    if (!fields.value || !fields.value.trim()) errors.value = 'กรุณาระบุค่า';
    return errors;
}

export function validateTransactionForm(fields: TransactionFormFields): Record<string, string> {
    const errors: Record<string, string> = {};
    if (!fields.symbol || !fields.symbol.trim()) errors.symbol = 'กรุณาระบุ symbol';
    if (!fields.qty || !fields.qty.trim()) errors.qty = 'กรุณาระบุจำนวน';
    if (!fields.price || !fields.price.trim()) errors.price = 'กรุณาระบุราคา';
    return errors;
}
