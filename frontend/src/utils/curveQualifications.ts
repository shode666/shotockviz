// bd:shotockviz-a6p — the equity sparkline's honesty layer, same shape/order
// convention as utils/portfolioQualifications.ts (bd:shotockviz-pxo): a pure
// function, worst-first, meant to render as ONE block above the chart it
// qualifies, and nothing at all when there is nothing to say.
//
// bd:shotockviz-la4's /portfolio/performance declares:
//   fx_basis = "single_currency"
//       Whole book in the base currency. No conversion, nothing to qualify.
//   fx_basis = "constant_current_rate"
//       A mixed book, every day converted at ONE rate — today's. The line
//       shows how the MARKET moved; it deliberately does not contain
//       currency return, and its historical levels are NOT what the book
//       was worth in THB on those dates.
// plus which symbols could not be placed on the curve at all
// (fx_unavailable_symbols, currency_conflict_symbols) — these can be
// non-empty even when fx_basis stays "single_currency" (e.g. a THB-only
// book with one symbol excluded for a currency conflict never sets the
// basis away from single_currency — see backend/services/portfolio_service.py
// curve_fx_plan()), so they are checked independently of fx_basis, not
// nested under the constant-rate case.

export type CurveQualificationTone = 'error' | 'warn' | 'info';

export interface CurveQualification {
    key: string;
    tone: CurveQualificationTone;
    text: string;
}

export interface CurvePerformanceInput {
    fx_basis?: string | null;
    fx_estimated?: boolean | null;
    fx_unavailable_symbols?: string[] | null;
    currency_conflict_symbols?: string[] | null;
}

const CURVE_BASIS_CONSTANT_RATE = 'constant_current_rate';

const list = (symbols: string[]) => symbols.join(', ');

/** Ordered, worst first. Empty array = the curve needs no qualification —
 * a THB-only book with no excluded symbols renders none of this. */
export function buildCurveQualifications(
    perf: CurvePerformanceInput | null | undefined
): CurveQualification[] {
    if (!perf) return [];
    const out: CurveQualification[] = [];

    // 1. Symbols excluded because their rows disagree on currency (rule 5) —
    //    data corruption, not a delay.
    const conflicts = perf.currency_conflict_symbols ?? [];
    if (conflicts.length > 0) {
        out.push({
            key: 'curve-currency-conflict',
            tone: 'error',
            text: `${list(conflicts)} — มีธุรกรรมหลายสกุลเงินในสัญลักษณ์เดียวกัน ไม่รวมในกราฟนี้`,
        });
    }

    // 2. Symbols excluded because no FX rate exists for their currency.
    const noRate = perf.fx_unavailable_symbols ?? [];
    if (noRate.length > 0) {
        out.push({
            key: 'curve-fx-unavailable',
            tone: 'warn',
            text: `${list(noRate)} — ไม่มีอัตราแลกเปลี่ยนสำหรับสกุลเงินนี้ ไม่รวมในกราฟนี้`,
        });
    }

    // 3. What the line itself is allowed to claim.
    if (perf.fx_basis === CURVE_BASIS_CONSTANT_RATE) {
        out.push({
            key: 'curve-constant-rate',
            tone: 'info',
            text: perf.fx_estimated
                ? 'แปลงทุกวันด้วยอัตราแลกเปลี่ยนปัจจุบัน (ประมาณการ) ไม่ใช่อัตราของแต่ละวันในอดีต — เส้นนี้แสดงการเคลื่อนไหวของราคาหุ้น ไม่ใช่ผลตอบแทนจากค่าเงิน'
                : 'แปลงทุกวันด้วยอัตราแลกเปลี่ยนปัจจุบัน ไม่ใช่อัตราของแต่ละวันในอดีต — เส้นนี้แสดงการเคลื่อนไหวของราคาหุ้น ไม่ใช่ผลตอบแทนจากค่าเงิน',
        });
    }

    return out;
}

/** True when there is anything at all to render above the sparkline. */
export function hasCurveQualifications(perf: CurvePerformanceInput | null | undefined): boolean {
    return buildCurveQualifications(perf).length > 0;
}
