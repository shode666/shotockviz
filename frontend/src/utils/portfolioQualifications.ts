// bd:shotockviz-pxo — what has to be said BEFORE the portfolio figures, and in
// what order.
//
// After bd:shotockviz-2w8 an all-unpriced book correctly reads 0 / 0 / 0 with
// `has_pending_prices=true` instead of fabricating a total loss. But the
// explanation rendered BELOW the holdings table, so the user met the zeros
// first and the reason second — or, on a short viewport, never. A qualification
// that arrives after the number it qualifies has already done its damage.
//
// bd:shotockviz-fnn then added a second disclosure (FX rates and their honesty)
// above the table. Two separate warning blocks stacked around the same figures
// is not a fix either. This module is the single ordered list of everything
// currently qualifying the totals, worst first, so the page can render ONE
// block in one place — above the stat cards, which is what the sentences are
// about.
//
// The rule: every sentence here names the symbols it is about and says what the
// totals DID with them (excluded), because "excluded" and "worth zero" are the
// two readings the user must never have to guess between.

export type QualificationTone = 'error' | 'warn' | 'info';

export interface Qualification {
    key: string;
    tone: QualificationTone;
    text: string;
}

export interface QualificationHolding {
    symbol: string;
    current_price?: number | null;
    currency_conflict?: boolean;
}

export interface QualificationInput {
    holdings?: QualificationHolding[] | null;
    has_pending_prices?: boolean;
    fx_pl?: number | null;
    cost_basis_estimated?: boolean;
    fx_estimated?: boolean;
    fx_unavailable_symbols?: string[] | null;
    currency_conflict_symbols?: string[] | null;
    fx_rates?: unknown[] | null;
}

const list = (symbols: string[]) => symbols.join(', ');

/**
 * Ordered, worst first. Empty array = the totals need no qualification, and the
 * page renders no block at all rather than an empty container.
 */
export function buildQualifications(a: QualificationInput | null | undefined): Qualification[] {
    if (!a) return [];
    const out: Qualification[] = [];

    // 1. Broken data. Not a delay — waiting will not fix it, so it must not be
    //    worded like the pending-price case (bd:shotockviz-7ju).
    const conflicts = a.currency_conflict_symbols ?? [];
    if (conflicts.length > 0) {
        out.push({
            key: 'currency-conflict',
            tone: 'error',
            text:
                `${list(conflicts)} — มีธุรกรรมมากกว่า 1 สกุลเงินในสัญลักษณ์เดียวกัน ` +
                `ต้นทุนจึงปนหน่วยเงินและคำนวณไม่ได้ ยอดรวมด้านล่างไม่รวมรายการเหล่านี้ ` +
                `กรุณาแก้สกุลเงินในประวัติธุรกรรมให้ตรงกัน`,
        });
    }

    // 2. bd:shotockviz-2w8's zeros. The sentence the user used to meet last.
    const pending = (a.holdings ?? [])
        .filter((h) => h.current_price == null && !h.currency_conflict)
        .map((h) => h.symbol);
    if (a.has_pending_prices && pending.length > 0) {
        out.push({
            key: 'pending-prices',
            tone: 'warn',
            text:
                `${list(pending)} — ยังไม่มีราคาล่าสุด ยอดรวมด้านล่างไม่รวมรายการเหล่านี้ ` +
                `(ไม่ได้แปลว่ามูลค่าเป็น 0) จะอัปเดตอัตโนมัติเมื่อข้อมูลพร้อม`,
        });
    }

    // 3. Priced, but no rate exists for its currency — excluded, never added raw.
    const noRate = a.fx_unavailable_symbols ?? [];
    if (noRate.length > 0) {
        out.push({
            key: 'fx-unavailable',
            tone: 'warn',
            text: `${list(noRate)} — ไม่มีอัตราแลกเปลี่ยนสำหรับสกุลเงินนี้ จึงไม่ถูกรวมในยอดรวมด้านล่าง`,
        });
    }

    // 4. The FX return itself. "ไม่ทราบ" is a different claim from 0.
    if (a.fx_rates && a.fx_rates.length > 0) {
        if (a.fx_pl == null) {
            out.push({
                key: 'fx-pl-unknown',
                tone: 'warn',
                text:
                    'ผลตอบแทนจากค่าเงิน: ไม่ทราบ — บางรายการซื้อไม่ได้บันทึกอัตราแลกเปลี่ยนไว้ ' +
                    'และระบบไม่ย้อนหลังอัตราเก่าให้',
            });
        }
        if (a.cost_basis_estimated) {
            out.push({
                key: 'cost-basis-estimated',
                tone: 'info',
                text: 'ต้นทุนบางรายการแปลงด้วยอัตราปัจจุบัน ไม่ใช่อัตราตอนซื้อ',
            });
        }
    }

    return out;
}

/** True when there is anything at all to render above the figures. */
export function hasQualifications(a: QualificationInput | null | undefined): boolean {
    if (!a) return false;
    return buildQualifications(a).length > 0 || (a.fx_rates?.length ?? 0) > 0;
}
