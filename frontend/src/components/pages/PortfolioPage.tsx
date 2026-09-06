import { useState, useMemo } from 'react';
import toast from 'react-hot-toast';
import { Briefcase, Trash2, Pencil, History, BarChart2, FilterX, Timer, AlertTriangle, Hourglass, Info } from 'lucide-react';
import portfolioService from '@/services/portfolioService';
import useAuthStore from '@/store/authStore';
import { displaySymbol, formatPriceTH } from '@/utils/formatters';
import { extractErrorMessage } from '@/services/apiErrorHandler';
import { AddTransactionModal, type EditableTransaction } from '@/components/portfolio/AddTransactionModal';
import { HoldingsTable } from '@/components/portfolio/HoldingsTable';
import { ConcentrationLimitPanel } from '@/components/portfolio/ConcentrationLimitPanel';
import { usePortfolioData } from '@/hooks/usePortfolioData';
import { buildQualifications, hasQualifications, realFxRates, type QualificationTone } from '@/utils/portfolioQualifications';
import { groupAllocation, donutSegments, exclusionSentence, hasAllocation } from '@/utils/allocation';

const CURR_SIGN: Record<string, string> = { THB: '฿', USD: '$' };

// bd:shotockviz-fnn — how an FX rate got here, in the user's words.
const FX_SOURCE_TH: Record<string, string> = {
    live: 'อัตราล่าสุดจากตลาด',
    last_known: 'ประมาณการ — ใช้อัตราที่คุณเคยบันทึกไว้ล่าสุด',
    fallback: 'ประมาณการ — ค่าเริ่มต้นของระบบ (ยังไม่เคยมีอัตราจริง)',
};

interface FxRateInfo {
    currency: string;
    base?: string;
    rate: number;
    source: string;
    as_of?: string | null;
    estimated?: boolean;
}

const TONE_ICON: Record<QualificationTone, typeof AlertTriangle> = {
    error: AlertTriangle,
    warn: Hourglass,
    info: Info,
};
const TONE_COLOR: Record<QualificationTone, string> = {
    error: 'var(--color-red)',
    warn: 'var(--color-yellow)',
    info: 'var(--color-text-sub)',
};

/**
 * bd:shotockviz-pxo — ONE qualification block, rendered above the figures it
 * qualifies.
 *
 * It replaces two disclosures that used to sit on either side of the numbers:
 * bd:shotockviz-fnn's FX note (above the table) and bd:shotockviz-2w8's
 * pending-price note (BELOW the table, so the user met the 0/0/0 first and the
 * reason second, or never). Stacking two warning blocks around the same totals
 * was not a fix; what the totals leave out and what the totals are estimated
 * from are the same statement and belong in the same place — before them.
 *
 * The sentences and their order live in `utils/portfolioQualifications.ts` and
 * are unit-tested; this component only renders them, plus the FX rate rows,
 * which stay structured so "ประมาณการ" can be a badge rather than prose.
 */
function BookQualifications({ analytics }: { analytics: any }) {
    if (!hasQualifications(analytics)) return null;
    const items = buildQualifications(analytics);
    // bd:shotockviz-q5o — identity rates (single-currency book) are excluded
    // here, not just from `items`: a "THB/THB 1.0000 · identity" row and the
    // FX-return line below it are noise when there is no FX dimension at all.
    const rates: FxRateInfo[] = realFxRates(analytics) as unknown as FxRateInfo[];
    const fxPl: number | null | undefined = analytics?.fx_pl;

    return (
        <div
            role="status"
            data-testid="portfolio-qualifications"
            className="text-[11px] mb-5 px-3 py-2.5 rounded-xl flex flex-col gap-1.5 border"
            style={{
                background: 'var(--color-hover)',
                color: 'var(--color-text-sub)',
                borderWidth: 1,
                borderStyle: 'solid',
                borderColor: 'var(--color-border)',
            }}
        >
            {items.map((q) => {
                const Icon = TONE_ICON[q.tone];
                return (
                    <div key={q.key} className="flex items-start gap-1.5">
                        <Icon size={12} strokeWidth={2} aria-hidden="true"
                            className="mt-[2px] shrink-0" style={{ color: TONE_COLOR[q.tone] }} />
                        <span style={q.tone === 'error' ? { color: 'var(--color-red)' } : undefined}>{q.text}</span>
                    </div>
                );
            })}

            {rates.map((r) => (
                <div key={r.currency} className="flex items-center gap-1.5 flex-wrap">
                    <span className="font-semibold">{r.currency}/{r.base ?? 'THB'} {formatPriceTH(r.rate, 4)}</span>
                    <span>· {FX_SOURCE_TH[r.source] ?? r.source}{r.as_of ? ` (${r.as_of})` : ''}</span>
                    {r.estimated && (
                        <span className="px-1.5 py-0.5 rounded text-[9px] font-semibold"
                            style={{ background: 'var(--color-yellow)', color: '#000' }}>ประมาณการ</span>
                    )}
                </div>
            ))}

            {/* A KNOWN currency return is a figure, not a caveat — the unknown
                case is already said above by `fx-pl-unknown`. */}
            {rates.length > 0 && fxPl != null && (
                <div>
                    ผลตอบแทนจากค่าเงิน:{' '}
                    <span className="font-semibold tabular-nums"
                        style={{ color: fxPl >= 0 ? 'var(--color-green)' : 'var(--color-red)' }}>
                        {fxPl >= 0 ? '+' : '-'}฿{formatPriceTH(Math.abs(fxPl))}
                    </span>
                </div>
            )}
        </div>
    );
}

/**
 * bd:shotockviz-916 / FR-PORT-002 — % allocation.
 *
 * The picture answers one question: how much of the book is in one name. So the
 * heaviest position is stated in words above the ring, not left to be judged by
 * eye from an arc.
 *
 * What it is a percentage OF is on the panel, not implied: the denominator is
 * the base-currency market value of the positions that could be stated — the
 * same number the "มูลค่ารวม" card prints — and every position left out of it is
 * named underneath with its reason. An excluded position gets no wedge at all,
 * because a 0% wedge says "worth nothing" and the truth is "not known"
 * (bd:shotockviz-2w8 / -7ju / -fnn; see build_allocation in
 * backend/services/portfolio_service.py).
 *
 * No charting dependency: `lightweight-charts` (package.json:25) draws time
 * series, and ADR-UH-003's no-new-deps NFR rules out adding one for a donut.
 * The arcs are `stroke-dasharray` on one circle per slice with `pathLength=100`,
 * and the fractions come from `utils/allocation.ts` (unit-tested), so the ring
 * closes on the values it is drawn from rather than on rounded percentages.
 */
function AllocationPanel({ analytics }: { analytics: any }) {
    const allocation = analytics?.allocation;
    if (!hasAllocation(allocation)) return null;

    const slices = groupAllocation(allocation);
    const segments = donutSegments(slices);
    const excluded = exclusionSentence(allocation);
    const approx = allocation?.fx_estimated ? '≈' : '';
    const top = slices.length > 0 && !slices[0].isOthers ? slices[0] : null;
    const qualified = slices.some((s) => s.qualified);

    return (
        <div
            data-testid="portfolio-allocation"
            className="panel border rounded-2xl p-4 mb-4"
            style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}
        >
            <div className="flex items-center gap-2 mb-1">
                <BarChart2 size={13} aria-hidden="true" />
                <h3 className="text-xs font-bold">สัดส่วนพอร์ต</h3>
            </div>
            {/* What the percentages are OF — stated, never implied. */}
            <p className="text-[11px] mb-3" style={{ color: 'var(--color-text-sub)' }}>
                คิดจากมูลค่าตลาดที่ระบุได้ {approx}฿{formatPriceTH(allocation?.total_value)} ({allocation?.base_currency ?? 'THB'})
            </p>

            {slices.length === 0 ? (
                <p className="text-[11px]" style={{ color: 'var(--color-yellow)' }}>
                    ยังไม่มีรายการที่ระบุมูลค่าได้ จึงยังแสดงสัดส่วนไม่ได้
                </p>
            ) : (
                <div className="flex flex-wrap items-center gap-5">
                    <svg
                        viewBox="0 0 42 42"
                        width={120}
                        height={120}
                        role="img"
                        aria-label={`สัดส่วนพอร์ตตามมูลค่า: ${slices
                            .map((s) => `${s.label} ${s.weight_pct.toFixed(1)}%`)
                            .join(', ')}`}
                        className="shrink-0"
                    >
                        <g transform="rotate(-90 21 21)">
                            {segments.map((seg, i) => (
                                <circle
                                    key={seg.key}
                                    cx="21"
                                    cy="21"
                                    r="15.9155"
                                    fill="none"
                                    stroke={slices[i].color}
                                    strokeWidth="6"
                                    pathLength={100}
                                    strokeDasharray={`${seg.dash} ${seg.gap}`}
                                    strokeDashoffset={seg.offset}
                                />
                            ))}
                        </g>
                    </svg>

                    <div className="flex-1 min-w-[200px]">
                        {top && (
                            <p className="text-[11px] mb-2">
                                หนักสุด{' '}
                                <span className="font-semibold" style={{ color: 'var(--color-accent-text)' }}>
                                    {displaySymbol(top.label)}
                                </span>{' '}
                                <span className="font-semibold tabular-nums">{top.weight_pct.toFixed(1)}%</span>
                            </p>
                        )}
                        <ul className="flex flex-col gap-1">
                            {slices.map((s) => (
                                <li key={s.key} className="flex items-center gap-2 text-[11px]">
                                    <span
                                        aria-hidden="true"
                                        className="w-2.5 h-2.5 rounded-sm shrink-0"
                                        style={{ background: s.color }}
                                    />
                                    <span className="truncate">
                                        {s.isOthers ? s.label : displaySymbol(s.label)}
                                        {/* Not aria-hidden: the footnote below it is
                                            real text, so the marker has to be
                                            reachable by the same reader. */}
                                        {s.qualified && <span> *</span>}
                                    </span>
                                    <span className="ml-auto tabular-nums font-semibold">
                                        {s.weight_pct.toFixed(1)}%
                                    </span>
                                    <span className="tabular-nums w-24 text-right" style={{ color: 'var(--color-text-sub)' }}>
                                        ฿{formatPriceTH(s.value_base)}
                                    </span>
                                </li>
                            ))}
                        </ul>
                    </div>
                </div>
            )}

            {qualified && (
                <p className="text-[10px] mt-3" style={{ color: 'var(--color-text-sub)' }}>
                    * จำนวนหุ้นถูกปรับตามการแตกพาร์ หรืออาจไม่ครบเพราะไม่ได้บันทึกการใช้สิทธิเพิ่มทุน
                </p>
            )}

            {/* The chart must never be readable without this line: a book whose
                excluded positions are invisible is a book that looks smaller and
                more concentrated than it is. */}
            {excluded && (
                <p className="text-[11px] mt-3 flex items-start gap-1.5" style={{ color: 'var(--color-text-sub)' }}>
                    <Hourglass size={12} strokeWidth={2} aria-hidden="true" className="mt-[2px] shrink-0"
                        style={{ color: 'var(--color-yellow)' }} />
                    <span>{excluded}</span>
                </p>
            )}
        </div>
    );
}

function StatCard({ label, value, sub, up }: { label: string; value: string | number; sub?: string; up?: boolean }) {
    return (
        <div className="panel border rounded-2xl p-4" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
            <div className="text-[10px] uppercase tracking-wider mb-2" style={{ color: 'var(--color-text-sub)' }}>{label}</div>
            <div className="text-xl font-bold tabular-nums">{value ?? '—'}</div>
            {sub != null && (
                <div className="text-xs mt-1 font-medium" style={{ color: up ? 'var(--color-green)' : 'var(--color-red)' }}>{sub}</div>
            )}
        </div>
    );
}

export default function PortfolioPage() {
    const { isAuthenticated, user } = useAuthStore();
    const { analytics, txns, loading, timedOut, reload } = usePortfolioData();
    const [showModal, setShowModal] = useState(false);
    // bd:shotockviz-gij — null = "add new" (existing button), set = editing
    // this row. AddTransactionModal renders both from the same JSX.
    const [editingTxn, setEditingTxn] = useState<EditableTransaction | null>(null);
    const [deletingId, setDeletingId] = useState<number | null>(null);
    const [activeTab, setActiveTab] = useState<'holdings' | 'history'>('holdings');
    const [historyFilter, setHistoryFilter] = useState<'ALL' | 'BUY' | 'SELL'>('ALL');
    const [filterSymbol, setFilterSymbol] = useState('');
    const [filterMonth, setFilterMonth] = useState('');

    const handleDelete = async (id: number) => {
        if (!confirm('ลบธุรกรรมนี้?')) return;
        setDeletingId(id);
        try {
            await portfolioService.deleteTransaction(id);
            toast.success('ลบธุรกรรมสำเร็จ');
            await reload();
        } catch (err: any) {
            // bd:shotockviz-gij — was reading `err.response.data.detail`, which
            // /api/v1's error envelope (schemas/envelope.py) no longer carries
            // (message moved to meta.error.message); this silently fell back to
            // axios's generic "Request failed with status code NNN". Same
            // extraction api.ts's global interceptor uses, so this toast and
            // that one always agree.
            toast.error(extractErrorMessage(err));
        } finally { setDeletingId(null); }
    };

    const openAddTxnModal = () => {
        setEditingTxn(null);
        setShowModal(true);
    };

    const openEditTxnModal = (t: EditableTransaction) => {
        setEditingTxn(t);
        setShowModal(true);
    };

    const closeTxnModal = () => {
        setShowModal(false);
        setEditingTxn(null);
    };

    const fmtQty = (n: number | null | undefined) => n != null ? parseFloat(n.toFixed(8)).toString() : '—';
    const pnlUp = analytics ? analytics.unrealized_pl >= 0 : true;
    const baseCurrency: string = analytics?.base_currency ?? 'THB';
    // bd:shotockviz-fnn — an estimated rate must be visible on the figure
    // itself, not only in the note below it.
    const fxApprox = (analytics?.fx_estimated || analytics?.cost_basis_estimated) ? '≈' : '';

    const THAI_MONTHS = ['ม.ค.', 'ก.พ.', 'มี.ค.', 'เม.ย.', 'พ.ค.', 'มิ.ย.', 'ก.ค.', 'ส.ค.', 'ก.ย.', 'ต.ค.', 'พ.ย.', 'ธ.ค.'];
    const fmtMonth = (ym: string) => {
        const [y, m] = ym.split('-');
        return `${THAI_MONTHS[parseInt(m) - 1]} ${y}`;
    };
    const uniqueSymbols = useMemo(() => [...new Set(txns.map(t => t.symbol))].sort(), [txns]);
    const uniqueMonths = useMemo(() =>
        [...new Set(txns.map(t => t.date?.slice(0, 7)))].filter(Boolean).sort().reverse(), [txns]);
    const filteredTxns = useMemo(() => txns.filter(t =>
        (historyFilter === 'ALL' || t.type === historyFilter) &&
        (!filterSymbol || t.symbol === filterSymbol) &&
        (!filterMonth || t.date?.startsWith(filterMonth))
    ), [txns, historyFilter, filterSymbol, filterMonth]);
    const hasFilters = historyFilter !== 'ALL' || filterSymbol !== '' || filterMonth !== '';
    const clearFilters = () => { setHistoryFilter('ALL'); setFilterSymbol(''); setFilterMonth(''); };

    return (
        <div className="flex-1 overflow-auto p-6" style={{ background: 'var(--color-bg)' }}>
            <div className="max-w-5xl mx-auto animate-fade-in">

                <div className="flex items-center justify-between mb-5">
                    <div>
                        <h2 className="text-base font-bold flex items-center gap-2"><Briefcase size={16} /> Portfolio</h2>
                        <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-sub)' }}>ติดตามพอร์ตการลงทุนของคุณ</p>
                    </div>
                    {isAuthenticated && (
                        <button onClick={openAddTxnModal} className="btn-accent">+ เพิ่มธุรกรรม</button>
                    )}
                </div>

                {!isAuthenticated ? (
                    <div className="panel border rounded-2xl p-8 text-center" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                        <div className="mb-3 flex justify-center"><Briefcase size={32} style={{ color: 'var(--color-text-sub)' }} /></div>
                        <p className="text-sm font-medium mb-1">กรุณาเข้าสู่ระบบ</p>
                        <p className="text-xs" style={{ color: 'var(--color-text-sub)' }}>Login เพื่อดูและจัดการพอร์ตการลงทุน</p>
                    </div>
                ) : loading ? (
                    <>
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
                            {[1, 2, 3, 4].map((i) => (
                                <div key={i} className="panel border rounded-2xl p-4 h-24 animate-pulse" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }} />
                            ))}
                        </div>
                        <div className="panel border rounded-2xl overflow-hidden animate-pulse" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                            <div className="px-4 py-3 border-b h-10" style={{ borderColor: 'var(--color-border)', background: 'var(--color-hover)' }}></div>
                            <div className="p-4 space-y-3">
                                {[1, 2, 3, 4].map(i => <div key={i} className="h-8 rounded" style={{ background: 'var(--color-hover)' }}></div>)}
                            </div>
                        </div>
                    </>
                ) : timedOut ? (
                    <div className="panel border rounded-2xl p-8 text-center animate-fade-in" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                        <Timer size={24} strokeWidth={2} className="mb-3 mx-auto" aria-hidden="true" style={{ color: 'var(--color-text-sub)' }} />
                        <p className="text-sm font-medium mb-1">Request timed out</p>
                        <p className="text-xs mb-4" style={{ color: 'var(--color-text-sub)' }}>ข้อมูลใช้เวลานานเกินไป — กรุณาลองใหม่</p>
                        <button onClick={reload} className="btn-accent">Retry</button>
                    </div>
                ) : (
                    <>
                        {/* bd:shotockviz-pxo — the qualification comes FIRST.
                            Everything the totals below exclude or estimate is
                            said here, before the reader can misread a 0. */}
                        <BookQualifications analytics={analytics} />

                        {/* Stats — bd:shotockviz-sbe: these are a THB-normalised
                            book total now (they used to be THB and USD added raw).
                            `≈` marks a total that leans on an estimated FX rate. */}
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
                            <StatCard label={`มูลค่ารวม (${baseCurrency})`} value={`${fxApprox}฿${formatPriceTH(analytics?.total_value)}`} />
                            <StatCard label={`ต้นทุนรวม (${baseCurrency})`} value={`${fxApprox}฿${formatPriceTH(analytics?.total_cost)}`} />
                            <StatCard
                                label="กำไร/ขาดทุน"
                                value={`${fxApprox}${pnlUp ? '+' : '-'}฿${formatPriceTH(analytics?.unrealized_pl != null ? Math.abs(analytics.unrealized_pl) : null)}`}
                                sub={`${pnlUp ? '+' : '-'}${formatPriceTH(analytics?.unrealized_pl_pct != null ? Math.abs(analytics.unrealized_pl_pct) : null)}%`}
                                up={pnlUp}
                            />
                            <StatCard label="จำนวนหุ้น" value={analytics?.holdings?.length ?? 0} />
                        </div>

                        {/* Tab Bar */}
                        <div className="flex items-center gap-1 mb-4 border-b" style={{ borderColor: 'var(--color-border)' }}>
                            <button
                                onClick={() => setActiveTab('holdings')}
                                className="flex items-center gap-1.5 px-4 py-2.5 text-xs font-semibold transition-colors relative"
                                style={{ color: activeTab === 'holdings' ? 'var(--color-accent-text)' : 'var(--color-text-sub)' }}
                            >
                                <BarChart2 size={13} />
                                Holdings
                                {analytics?.holdings?.length > 0 && (
                                    <span className="ml-1 text-[9px] px-1.5 py-0.5 rounded-full" style={{ background: activeTab === 'holdings' ? 'var(--color-accent-strong)' : 'var(--color-hover)', color: activeTab === 'holdings' ? '#fff' : 'var(--color-text-sub)' }}>
                                        {analytics.holdings.length}
                                    </span>
                                )}
                                {activeTab === 'holdings' && (
                                    <span className="absolute bottom-0 left-0 right-0 h-0.5 rounded-t-full" style={{ background: 'var(--color-accent)' }} />
                                )}
                            </button>
                            <button
                                onClick={() => setActiveTab('history')}
                                className="flex items-center gap-1.5 px-4 py-2.5 text-xs font-semibold transition-colors relative"
                                style={{ color: activeTab === 'history' ? 'var(--color-accent-text)' : 'var(--color-text-sub)' }}
                            >
                                <History size={13} />
                                ประวัติธุรกรรม
                                {txns.length > 0 && (
                                    <span className="ml-1 text-[9px] px-1.5 py-0.5 rounded-full" style={{ background: activeTab === 'history' ? 'var(--color-accent-strong)' : 'var(--color-hover)', color: activeTab === 'history' ? '#fff' : 'var(--color-text-sub)' }}>
                                        {txns.length}
                                    </span>
                                )}
                                {activeTab === 'history' && (
                                    <span className="absolute bottom-0 left-0 right-0 h-0.5 rounded-t-full" style={{ background: 'var(--color-accent)' }} />
                                )}
                            </button>
                        </div>

                        {/* Tab: Holdings */}
                        {/* bd:shotockviz-pxo — the note that used to sit here,
                            below the table, moved into <BookQualifications />
                            above the stat cards. Nothing is rendered after the
                            figures it explains. */}
                        {activeTab === 'holdings' && (
                            <>
                                {/* bd:shotockviz-916 — the same book as the table
                                    below and the totals above; one computation
                                    (services/portfolio_service.py), three views. */}
                                <AllocationPanel analytics={analytics} />
                                {/* bd:shotockviz-649 — the same % breakdown, checked
                                    against a threshold he sets, not just displayed. */}
                                <ConcentrationLimitPanel analytics={analytics} userId={user?.id ?? null} />
                                <HoldingsTable holdings={analytics?.holdings ?? []} hasPendingPrices={analytics?.has_pending_prices ?? false} />
                            </>
                        )}

                        {/* Tab: Transaction History */}
                        {activeTab === 'history' && (
                            <div className="panel border rounded-2xl overflow-hidden" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                                {/* Filter bar */}
                                <div className="px-4 py-3 border-b flex flex-wrap items-center gap-2" style={{ borderColor: 'var(--color-border)', background: 'var(--color-hover)' }}>
                                    {/* BUY/SELL/ALL toggle */}
                                    <div className="flex rounded-lg overflow-hidden text-[10px]" style={{ background: 'var(--color-input-bg)' }}>
                                        {(['ALL', 'BUY', 'SELL'] as const).map(f => (
                                            <button key={f} onClick={() => setHistoryFilter(f)}
                                                className="px-3 py-1.5 font-semibold transition-all"
                                                style={{
                                                    background: historyFilter === f ? 'var(--color-accent-strong)' : 'transparent',
                                                    color: historyFilter === f ? '#fff' : 'var(--color-text-sub)',
                                                }}>
                                                {f === 'ALL' ? 'ทั้งหมด' : f === 'BUY' ? 'ซื้อ' : 'ขาย'}
                                            </button>
                                        ))}
                                    </div>

                                    {/* Symbol dropdown */}
                                    <select
                                        value={filterSymbol}
                                        onChange={e => setFilterSymbol(e.target.value)}
                                        className="text-[10px] font-semibold px-2 py-1.5 rounded-lg outline-none transition-all"
                                        style={{
                                            background: filterSymbol ? 'var(--color-accent-strong)' : 'var(--color-input-bg)',
                                            color: filterSymbol ? '#fff' : 'var(--color-text-sub)',
                                            border: 'none',
                                            cursor: 'pointer',
                                        }}
                                    >
                                        <option value="">ทุก Symbol</option>
                                        {uniqueSymbols.map(s => <option key={s} value={s}>{s}</option>)}
                                    </select>

                                    {/* Month dropdown */}
                                    <select
                                        value={filterMonth}
                                        onChange={e => setFilterMonth(e.target.value)}
                                        className="text-[10px] font-semibold px-2 py-1.5 rounded-lg outline-none transition-all"
                                        style={{
                                            background: filterMonth ? 'var(--color-accent-strong)' : 'var(--color-input-bg)',
                                            color: filterMonth ? '#fff' : 'var(--color-text-sub)',
                                            border: 'none',
                                            cursor: 'pointer',
                                        }}
                                    >
                                        <option value="">ทุกเดือน</option>
                                        {uniqueMonths.map(m => <option key={m} value={m}>{fmtMonth(m)}</option>)}
                                    </select>

                                    {/* Clear filters + count */}
                                    <div className="ml-auto flex items-center gap-2">
                                        {hasFilters && (
                                            <button onClick={clearFilters}
                                                className="flex items-center gap-1 text-[10px] px-2 py-1.5 rounded-lg font-semibold transition-colors"
                                                style={{ background: 'var(--color-input-bg)', color: 'var(--color-text-sub)' }}
                                                onMouseEnter={e => (e.currentTarget.style.color = 'var(--color-red)')}
                                                onMouseLeave={e => (e.currentTarget.style.color = 'var(--color-text-sub)')}
                                                title="ล้าง filter">
                                                <FilterX size={11} /> ล้าง
                                            </button>
                                        )}
                                        <span className="text-[10px] font-semibold tabular-nums" style={{ color: 'var(--color-text-sub)' }}>
                                            {filteredTxns.length} รายการ
                                        </span>
                                    </div>
                                </div>

                                {txns.length === 0 ? (
                                    <div className="p-8 text-center">
                                        <div className="mb-3 flex justify-center"><History size={32} style={{ color: 'var(--color-text-sub)' }} /></div>
                                        <p className="text-sm font-medium mb-1">ยังไม่มีธุรกรรม</p>
                                        <p className="text-xs mb-4" style={{ color: 'var(--color-text-sub)' }}>เพิ่มธุรกรรมซื้อ/ขายเพื่อดูประวัติ</p>
                                        <button onClick={openAddTxnModal} className="btn-accent">+ เพิ่มธุรกรรม</button>
                                    </div>
                                ) : (
                                    <div className="overflow-x-auto">
                                        <table className="w-full">
                                            <thead>
                                                <tr className="text-[10px] border-b" style={{ color: 'var(--color-text-sub)', borderColor: 'var(--color-border)' }}>
                                                    {['วันที่', 'Symbol', 'ประเภท', 'จำนวน', 'ราคา/หุ้น', 'ค่าคอม', 'มูลค่ารวม', 'หมายเหตุ', ''].map(h => (
                                                        <th key={h} className="text-left px-4 py-2 font-medium whitespace-nowrap">{h}</th>
                                                    ))}
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {filteredTxns.map((t) => {
                                                    const isBuy = t.type === 'BUY';
                                                    const cs = CURR_SIGN[t.currency] ?? '฿';
                                                    const total = t.qty * t.price;
                                                    return (
                                                        <tr key={t.id} className="border-b text-xs transition-colors"
                                                            style={{ borderColor: 'var(--color-border)' }}
                                                            onMouseEnter={e => (e.currentTarget.style.background = 'var(--color-hover)')}
                                                            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                                                            <td className="px-4 py-3 tabular-nums whitespace-nowrap" style={{ color: 'var(--color-text-sub)' }}>{t.date}</td>
                                                            <td className="px-4 py-3 font-semibold whitespace-nowrap" style={{ color: 'var(--color-accent-text)' }}>
                                                                {displaySymbol(t.symbol)}
                                                                <span className="ml-1 text-[9px] px-1 py-0.5 rounded font-normal" style={{ background: 'var(--color-hover)', color: 'var(--color-text-sub)' }}>
                                                                    {t.currency ?? 'THB'}
                                                                </span>
                                                            </td>
                                                            <td className="px-4 py-3">
                                                                <span className="px-2 py-0.5 rounded-full text-[10px] font-semibold"
                                                                    style={{
                                                                        background: isBuy ? 'rgba(52,211,153,0.15)' : 'rgba(248,113,113,0.15)',
                                                                        color: isBuy ? 'var(--color-green)' : 'var(--color-red)',
                                                                    }}>
                                                                    {isBuy ? '▲ ซื้อ' : '▼ ขาย'}
                                                                </span>
                                                            </td>
                                                            <td className="px-4 py-3 tabular-nums">{fmtQty(t.qty)}</td>
                                                            <td className="px-4 py-3 tabular-nums">{cs}{formatPriceTH(t.price)}</td>
                                                            <td className="px-4 py-3 tabular-nums" style={{ color: 'var(--color-text-sub)' }}>{t.fee ? `${cs}${formatPriceTH(t.fee)}` : '—'}</td>
                                                            <td className="px-4 py-3 tabular-nums font-medium">{cs}{formatPriceTH(total)}</td>
                                                            <td className="px-4 py-3 max-w-[120px] truncate" style={{ color: 'var(--color-text-sub)' }} title={t.note}>{t.note || '—'}</td>
                                                            <td className="px-4 py-3">
                                                                <div className="flex items-center gap-1">
                                                                    <button
                                                                        onClick={() => openEditTxnModal(t)}
                                                                        disabled={deletingId === t.id}
                                                                        className="p-1.5 rounded-lg transition-colors"
                                                                        style={{ color: 'var(--color-text-sub)' }}
                                                                        onMouseEnter={e => (e.currentTarget.style.color = 'var(--color-accent-text)')}
                                                                        onMouseLeave={e => (e.currentTarget.style.color = 'var(--color-text-sub)')}
                                                                        title="แก้ไขธุรกรรม"
                                                                        aria-label={`แก้ไขธุรกรรม ${displaySymbol(t.symbol)}`}
                                                                    >
                                                                        <Pencil size={12} />
                                                                    </button>
                                                                    <button
                                                                        onClick={() => handleDelete(t.id)}
                                                                        disabled={deletingId === t.id}
                                                                        className="p-1.5 rounded-lg transition-colors"
                                                                        style={{ color: 'var(--color-text-sub)' }}
                                                                        onMouseEnter={e => (e.currentTarget.style.color = 'var(--color-red)')}
                                                                        onMouseLeave={e => (e.currentTarget.style.color = 'var(--color-text-sub)')}
                                                                        title="ลบธุรกรรม"
                                                                        aria-label={`ลบธุรกรรม ${displaySymbol(t.symbol)}`}
                                                                    >
                                                                        {deletingId === t.id
                                                                            ? <span style={{ display: 'inline-block', width: 12, height: 12, border: '2px solid currentColor', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.65s linear infinite' }} />
                                                                            : <Trash2 size={12} />}
                                                                    </button>
                                                                </div>
                                                            </td>
                                                        </tr>
                                                    );
                                                })}
                                            </tbody>
                                        </table>
                                        {filteredTxns.length === 0 && (
                                            <div className="text-center py-8 text-xs" style={{ color: 'var(--color-text-sub)' }}>
                                                ไม่พบรายการที่ตรงกับ filter ที่เลือก
                                            </div>
                                        )}
                                    </div>
                                )}
                            </div>
                        )}
                    </>
                )}
            </div>

            {/* Add Transaction Modal */}
            <AddTransactionModal isOpen={showModal} onClose={closeTxnModal} onSuccess={reload} transaction={editingTxn} />
        </div>
    );
}
