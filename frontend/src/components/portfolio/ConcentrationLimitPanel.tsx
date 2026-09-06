import { useEffect, useState } from 'react';
import { AlertTriangle, ShieldAlert } from 'lucide-react';
import api from '@/services/api';
import { didClearAuthSession } from '@/services/apiErrorHandler';
import { displaySymbol, formatPriceTH } from '@/utils/formatters';
import { hasAllocation } from '@/utils/allocation';
import {
    DEFAULT_CONCENTRATION_LIMIT_PCT,
    MIN_CONCENTRATION_LIMIT_PCT,
    MAX_CONCENTRATION_LIMIT_PCT,
    isValidConcentrationLimitPct,
    loadConcentrationLimitPct,
    saveConcentrationLimitPct,
    hasConcentrationBreach,
    notCheckedSentence,
    type ConcentrationInput,
} from '@/utils/concentrationLimit';

interface ConcentrationLimitPanelProps {
    /** The page's own `/portfolio/analytics` result — read ONLY for
     * `allocation` (unaffected by the limit) to decide whether there is
     * anything to check yet. Never re-derives the breach itself. */
    analytics: any;
    userId: number | string | null | undefined;
}

/**
 * bd:shotockviz-649 / bd:shotockviz-649.1 — "concentration as a limit, not
 * just a display" / "...no server-side per-user setting".
 *
 * bd:shotockviz-916's `AllocationPanel` (PortfolioPage.tsx) lets him SEE the
 * % breakdown; this TELLS him when a name crosses a threshold he set,
 * instead of asking him to re-read the donut every session.
 *
 * Fetches its OWN copy of `GET /portfolio/analytics?concentration_limit_pct=`
 * rather than reading a field off the page's already-fetched `analytics`:
 * that query param is the input that changes the instant he edits the
 * threshold, and `usePortfolioData()` (out of this bead's file scope, see
 * hand-off) fetches the book with no such param at all. This mirrors the
 * pattern `usePortfolioData` itself already uses for its own out-of-band
 * refetches (pending-price retry, WS `data_ready`) — a second targeted GET
 * against a CQRS read endpoint (Redis/Postgres only, no external call) is a
 * bounded, cheap cost, not a new architecture.
 *
 * The breach math is never duplicated here — see
 * `services/portfolio_service.py::build_concentration_check` (single source)
 * and `utils/concentrationLimit.ts` (this file's only local logic: bounds
 * validation, localStorage persistence, and the "not checked" sentence).
 *
 * WHERE THE LIMIT LIVES (bd:shotockviz-649.1): `GET/PATCH /settings/trader`
 * (`users.concentration_limit_pct`, api/routes/settings.py) is now the
 * source of truth, so the choice follows the trader across devices.
 * `utils/concentrationLimit.ts`'s localStorage helpers are kept as a
 * same-device CACHE only — they make the initial render feel instant
 * before the settings GET below resolves, and they are what the number
 * degrades to if that GET fails (never worse than bd:shotockviz-649's
 * original behaviour, never claimed as "saved" when it wasn't). A PATCH
 * failure is surfaced inline (`saveError` below) — bd:shotockviz-649.1's
 * acceptance criteria is explicit that a limit the trader believes is
 * saved and is not is worse than no limit at all, so this must never show
 * "saved" on a rejected or failed request.
 */
export function ConcentrationLimitPanel({ analytics, userId }: ConcentrationLimitPanelProps) {
    const [limitPct, setLimitPct] = useState<number>(() => loadConcentrationLimitPct(userId));
    const [inputValue, setInputValue] = useState<string>(() => String(loadConcentrationLimitPct(userId)));
    const [inputError, setInputError] = useState<string | null>(null);
    const [saveError, setSaveError] = useState<string | null>(null);
    const [saving, setSaving] = useState(false);
    const [concentration, setConcentration] = useState<ConcentrationInput | null>(null);
    const [loading, setLoading] = useState(false);

    // Re-sync if the signed-in user changes mid-session (e.g. a shared
    // browser). No-op re-render when the value already matches (React bails
    // out on an equal primitive), so this does NOT double the fetch below on
    // the normal mount.
    useEffect(() => {
        if (userId == null) return;
        const restored = loadConcentrationLimitPct(userId);
        setLimitPct(restored);
        setInputValue(String(restored));
    }, [userId]);

    // bd:shotockviz-649.1 — hydrate from the trader's SAVED server-side
    // value once per user. Runs after the localStorage restore above so the
    // input never flashes empty; if the trader has a saved value it wins
    // (it is the cross-device truth), if the GET fails or the trader has
    // genuinely never set one (`null`), the localStorage/default value from
    // above is left standing — never worse than bd:shotockviz-649.
    useEffect(() => {
        if (userId == null) return;
        let cancelled = false;
        // bd:shotockviz-tjh — this GET is decoration (see the doc comment
        // above): the panel already renders from the localStorage/default
        // value and this only upgrades it if a saved server value shows up.
        // `skipAuthClearOn401` opts it out of the global 401 handler
        // (services/apiErrorHandler.ts) so a 401 here — which this .catch
        // already swallows — cannot log the trader out of a page this
        // request isn't load-bearing for. The explicit PATCH below (Save
        // button) is a real user action and is NOT flagged: a genuinely
        // expired session must still log them out when they submit it.
        api.get('/settings/trader', { skipAuthClearOn401: true })
            .then((res) => {
                if (cancelled) return;
                const saved = res.data?.concentration_limit_pct;
                if (saved != null && isValidConcentrationLimitPct(saved)) {
                    setLimitPct(saved);
                    setInputValue(String(saved));
                    saveConcentrationLimitPct(userId, saved); // keep the device cache aligned
                }
            })
            .catch(() => {
                // Degrade to the localStorage/default value already set —
                // never block the panel on this fetch.
            });
        return () => { cancelled = true; };
    }, [userId]);

    const hasBook = hasAllocation(analytics?.allocation);

    useEffect(() => {
        if (!hasBook || userId == null) return;
        let cancelled = false;
        setLoading(true);
        api.get('/portfolio/analytics', { params: { concentration_limit_pct: limitPct } })
            .then((res) => {
                if (!cancelled) setConcentration(res.data?.concentration ?? null);
            })
            .catch(() => {
                // A failed check must not block the rest of the page — the
                // totals and the allocation panel above already rendered
                // from the main fetch. Degrading this ONE signal to
                // "unknown" (never rendered) is the honest outcome, not a
                // page-wide error.
                if (!cancelled) setConcentration(null);
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => { cancelled = true; };
    }, [hasBook, userId, limitPct]);

    if (!hasBook) return null;

    const handleSave = async () => {
        const parsed = Number(inputValue);
        if (!isValidConcentrationLimitPct(parsed)) {
            setInputError(`ระบุตัวเลข ${MIN_CONCENTRATION_LIMIT_PCT}-${MAX_CONCENTRATION_LIMIT_PCT}`);
            return;
        }
        setInputError(null);
        setSaveError(null);
        setSaving(true);
        try {
            // bd:shotockviz-649.1 — the server write IS the save; localStorage
            // is only updated AFTER it succeeds, so a failed PATCH never
            // leaves the trader believing a value is saved when the server
            // never accepted it (the interceptor also toasts the backend's
            // own error detail, e.g. an out-of-range value).
            await api.patch('/settings/trader', { concentration_limit_pct: parsed });
            saveConcentrationLimitPct(userId, parsed);
            setLimitPct(parsed); // triggers the effect above -> re-check against the server
        } catch (err) {
            // bd:shotockviz-2qw — a 401 here is a LOGOUT, not a rejected
            // save: PATCH is deliberately not flagged `skipAuthClearOn401`
            // (bd:shotockviz-tjh), so the interceptor has already cleared the
            // session. Showing "try again" on top of that invites the trader
            // to retry a form they no longer have a session for.
            if (!didClearAuthSession(err)) {
                setSaveError('บันทึกไม่สำเร็จ — ค่าที่แสดงอยู่อาจไม่ตรงกับที่บันทึกไว้ ลองใหม่อีกครั้ง');
            }
        } finally {
            setSaving(false);
        }
    };

    const breached = hasConcentrationBreach(concentration);
    const notChecked = notCheckedSentence(concentration);

    return (
        <div
            data-testid="concentration-limit"
            className="panel border rounded-2xl p-4 mb-4"
            style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}
        >
            <div className="flex items-center gap-2 mb-1">
                <ShieldAlert size={13} aria-hidden="true" />
                <h3 className="text-xs font-bold">ขีดจำกัดความเข้มข้นต่อชื่อ</h3>
            </div>
            <p className="text-[11px] mb-3" style={{ color: 'var(--color-text-sub)' }}>
                แจ้งเตือนเมื่อหุ้นตัวใดตัวหนึ่งเกินสัดส่วนที่กำหนดของพอร์ต — คิดจากมูลค่าตลาดเดียวกับ &quot;สัดส่วนพอร์ต&quot; ด้านบน
            </p>

            <div className="flex items-center gap-2 mb-1 flex-wrap">
                <label htmlFor="concentration-limit-input" className="text-[11px]" style={{ color: 'var(--color-text-sub)' }}>
                    ขีดจำกัดต่อชื่อ
                </label>
                <input
                    id="concentration-limit-input"
                    type="number"
                    min={MIN_CONCENTRATION_LIMIT_PCT}
                    max={MAX_CONCENTRATION_LIMIT_PCT}
                    value={inputValue}
                    onChange={(e) => setInputValue(e.target.value)}
                    className="w-20 text-xs px-2 py-1 rounded-lg outline-none"
                    style={{ background: 'var(--color-input-bg)', border: '1px solid var(--color-border)' }}
                    aria-describedby={inputError || saveError ? 'concentration-limit-error' : undefined}
                    disabled={saving}
                />
                <span className="text-[11px]" style={{ color: 'var(--color-text-sub)' }}>%</span>
                <button onClick={handleSave} disabled={saving} className="btn-accent text-[11px] px-3 py-1 disabled:opacity-60">
                    {saving ? 'กำลังบันทึก…' : 'บันทึก'}
                </button>
                {loading && (
                    <span className="text-[10px]" style={{ color: 'var(--color-text-sub)' }}>กำลังตรวจสอบ…</span>
                )}
            </div>
            {(inputError || saveError) && (
                <p id="concentration-limit-error" role="alert" className="text-[11px] mb-2" style={{ color: 'var(--color-red)' }}>
                    {inputError || saveError}
                </p>
            )}

            {breached ? (
                <ul role="alert" className="flex flex-col gap-1.5 mt-2">
                    {(concentration?.breaches ?? []).map((b) => (
                        <li key={b.symbol} className="flex items-start gap-1.5 text-[11px]" style={{ color: 'var(--color-red)' }}>
                            <AlertTriangle size={12} strokeWidth={2} aria-hidden="true" className="mt-[2px] shrink-0" />
                            <span>
                                <span className="font-semibold">{displaySymbol(b.symbol)}</span>{' '}
                                {b.weight_pct.toFixed(1)}% — เกินขีดจำกัด {b.limit_pct.toFixed(0)}% ไป {b.excess_pct.toFixed(1)} จุด
                                {' · '}ลดประมาณ ฿{formatPriceTH(b.trim_value_base)} เพื่อกลับเข้าเกณฑ์
                            </span>
                        </li>
                    ))}
                </ul>
            ) : (
                !loading && concentration != null && (
                    <p className="text-[11px] mt-2" style={{ color: 'var(--color-text-sub)' }}>
                        ยังไม่มีหุ้นตัวใดเกิน {limitPct}% ของพอร์ต
                    </p>
                )
            )}

            {notChecked && (
                <p className="text-[10px] mt-3 flex items-start gap-1.5" style={{ color: 'var(--color-text-sub)' }}>
                    <AlertTriangle size={11} strokeWidth={2} aria-hidden="true" className="mt-[2px] shrink-0" style={{ color: 'var(--color-yellow)' }} />
                    <span>{notChecked}</span>
                </p>
            )}
        </div>
    );
}
