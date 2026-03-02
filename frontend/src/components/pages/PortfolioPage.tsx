import { useState, useEffect, useCallback } from 'react';
import { Briefcase, TrendingUp, TrendingDown, X, Trash2, History, ChevronDown, ChevronUp } from 'lucide-react';
import portfolioService from '@/services/portfolioService';
import useAuthStore from '@/store/authStore';

const TXN_FORM_INIT = { symbol: '', type: 'BUY', qty: '', price: '', fee: '0', currency: 'THB', date: new Date().toISOString().slice(0, 10), note: '' };

// Auto-detect currency: .BK suffix = THB, anything else = USD
const detectCurrency = (symbol: string): 'THB' | 'USD' =>
    symbol.trim().toUpperCase().endsWith('.BK') ? 'THB' : symbol.trim() ? 'USD' : 'THB';

const CURR_SIGN: Record<string, string> = { THB: '฿', USD: '$' };

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
    const { isAuthenticated } = useAuthStore();
    const [analytics, setAnalytics] = useState(null);
    const [txns, setTxns] = useState<any[]>([]);
    const [loading, setLoading] = useState(false);
    const [timedOut, setTimedOut] = useState(false);
    const [showModal, setShowModal] = useState(false);
    const [form, setForm] = useState(TXN_FORM_INIT);
    const [saving, setSaving] = useState(false);
    const [deletingId, setDeletingId] = useState<number | null>(null);
    const [showHistory, setShowHistory] = useState(true);
    const [historyFilter, setHistoryFilter] = useState<'ALL' | 'BUY' | 'SELL'>('ALL');

    const load = useCallback(async () => {
        if (!isAuthenticated) return;
        setLoading(true);
        setTimedOut(false);
        try {
            const [analyticsRes, txnsRes] = await Promise.all([
                portfolioService.getAnalytics(),
                portfolioService.getTransactions(),
            ]);
            setAnalytics(analyticsRes.data);
            setTxns(txnsRes.data ?? []);
        } catch (err: any) {
            if (err?.code === 'ECONNABORTED' || err?.message?.includes('timeout')) {
                setTimedOut(true);
            }
        } finally { setLoading(false); }
    }, [isAuthenticated]);

    useEffect(() => { load(); }, [load]);

    const handleSymbolChange = (val: string) => {
        setForm((f) => ({ ...f, symbol: val, currency: detectCurrency(val) }));
    };

    const handleAdd = async () => {
        if (!form.symbol || !form.qty || !form.price) return;
        setSaving(true);
        try {
            await portfolioService.addTransaction({
                symbol: form.symbol.toUpperCase(),
                type: form.type,
                qty: parseFloat(form.qty),
                price: parseFloat(form.price),
                fee: parseFloat(form.fee) || 0,
                currency: form.currency,
                date: form.date,
                note: form.note,
            });
            setShowModal(false);
            setForm(TXN_FORM_INIT);
            load();
        } finally { setSaving(false); }
    };

    const handleDelete = async (id: number) => {
        if (!confirm('ลบธุรกรรมนี้?')) return;
        setDeletingId(id);
        try {
            await portfolioService.deleteTransaction(id);
            await load();
        } finally { setDeletingId(null); }
    };

    const fmt = (n, decimals = 2) => n?.toLocaleString('th-TH', { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) ?? '—';
    const fmtQty = (n) => n != null ? parseFloat(n.toFixed(8)).toString() : '—';
    const pnlUp = analytics ? analytics.unrealized_pl >= 0 : true;

    return (
        <div className="flex-1 overflow-auto p-6" style={{ background: 'var(--color-bg)' }}>
            <div className="max-w-5xl mx-auto animate-fade-in">

                <div className="flex items-center justify-between mb-5">
                    <div>
                        <h2 className="text-base font-bold flex items-center gap-2"><Briefcase size={16} /> Portfolio</h2>
                        <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-sub)' }}>ติดตามพอร์ตการลงทุนของคุณ</p>
                    </div>
                    {isAuthenticated && (
                        <button onClick={() => setShowModal(true)} className="btn-accent">+ เพิ่มธุรกรรม</button>
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
                        <div className="text-3xl mb-3">⏱</div>
                        <p className="text-sm font-medium mb-1">Request timed out</p>
                        <p className="text-xs mb-4" style={{ color: 'var(--color-text-sub)' }}>ข้อมูลใช้เวลานานเกินไป — กรุณาลองใหม่</p>
                        <button onClick={load} className="btn-accent">Retry</button>
                    </div>
                ) : (
                    <>
                        {/* Stats */}
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
                            <StatCard label="มูลค่ารวม" value={`฿${fmt(analytics?.total_value)}`} />
                            <StatCard label="ต้นทุนรวม" value={`฿${fmt(analytics?.total_cost)}`} />
                            <StatCard
                                label="กำไร/ขาดทุน"
                                value={`${pnlUp ? '+' : ''}฿${fmt(analytics?.unrealized_pl)}`}
                                sub={`${pnlUp ? '+' : ''}${fmt(analytics?.unrealized_pl_pct)}%`}
                                up={pnlUp}
                            />
                            <StatCard label="จำนวนหุ้น" value={analytics?.holdings?.length ?? 0} />
                        </div>

                        {/* Holdings */}
                        {!analytics?.holdings?.length ? (
                            <div className="panel border rounded-2xl p-8 text-center" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                                <div className="mb-3 flex justify-center"><Briefcase size={32} style={{ color: 'var(--color-text-sub)' }} /></div>
                                <p className="text-sm font-medium mb-1">ยังไม่มีหุ้นในพอร์ต</p>
                                <p className="text-xs mb-4" style={{ color: 'var(--color-text-sub)' }}>เพิ่มธุรกรรมซื้อ/ขายเพื่อเริ่มติดตามพอร์ต</p>
                                <button onClick={() => setShowModal(true)} className="btn-accent">+ เพิ่มธุรกรรม</button>
                            </div>
                        ) : (
                            <div className="panel border rounded-2xl overflow-hidden" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                                <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
                                    <span className="text-xs font-semibold">Holdings ({analytics.holdings.length} หุ้น)</span>
                                </div>
                                <table className="w-full">
                                    <thead>
                                        <tr className="text-[10px] border-b" style={{ color: 'var(--color-text-sub)', borderColor: 'var(--color-border)' }}>
                                            {['Symbol', 'จำนวน', 'ต้นทุนเฉลี่ย', 'ราคาปัจจุบัน', 'มูลค่า', 'กำไร/ขาดทุน', '%'].map((h) => (
                                                <th key={h} className="text-left px-4 py-2 font-medium">{h}</th>
                                            ))}
                                        </tr>
                                    </thead>
                                    <tbody>
                                        {analytics.holdings.map((h) => {
                                            const up = (h.unrealized_pl ?? 0) >= 0;
                                            const cs = CURR_SIGN[h.currency] ?? '฿';
                                            return (
                                                <tr key={h.symbol} className="border-b text-xs" style={{ borderColor: 'var(--color-border)' }}>
                                                    <td className="px-4 py-3 font-semibold" style={{ color: 'var(--color-accent)' }}>
                                                        {h.symbol}
                                                        <span className="ml-1.5 text-[9px] px-1 py-0.5 rounded font-normal" style={{ background: 'var(--color-hover)', color: 'var(--color-text-sub)' }}>
                                                            {h.currency ?? 'THB'}
                                                        </span>
                                                    </td>
                                                    <td className="px-4 py-3 tabular-nums">{h.qty.toLocaleString()}</td>
                                                    <td className="px-4 py-3 tabular-nums">{cs}{fmt(h.avg_cost)}</td>
                                                    <td className="px-4 py-3 tabular-nums">{h.current_price != null ? `${cs}${fmt(h.current_price)}` : '—'}</td>
                                                    <td className="px-4 py-3 tabular-nums">{h.current_value != null ? `${cs}${fmt(h.current_value)}` : '—'}</td>
                                                    <td className="px-4 py-3 tabular-nums font-medium" style={{ color: up ? 'var(--color-green)' : 'var(--color-red)' }}>
                                                        {h.unrealized_pl != null ? `${up ? '+' : ''}${cs}${fmt(h.unrealized_pl)}` : '—'}
                                                    </td>
                                                    <td className="px-4 py-3 tabular-nums" style={{ color: up ? 'var(--color-green)' : 'var(--color-red)' }}>
                                                        {h.unrealized_pl_pct != null ? `${up ? '+' : ''}${fmt(h.unrealized_pl_pct)}%` : '—'}
                                                    </td>
                                                </tr>
                                            );
                                        })}
                                    </tbody>
                                </table>
                            </div>
                        )}
                        {/* Transaction History */}
                        {txns.length > 0 && (
                            <div className="mt-5 panel border rounded-2xl overflow-hidden" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                                {/* Header */}
                                <div className="px-4 py-3 border-b flex items-center justify-between" style={{ borderColor: 'var(--color-border)' }}>
                                    <button
                                        className="flex items-center gap-2 text-xs font-semibold"
                                        onClick={() => setShowHistory(v => !v)}
                                    >
                                        <History size={13} style={{ color: 'var(--color-accent)' }} />
                                        ประวัติธุรกรรม ({txns.length} รายการ)
                                        {showHistory ? <ChevronUp size={12} style={{ color: 'var(--color-text-sub)' }} /> : <ChevronDown size={12} style={{ color: 'var(--color-text-sub)' }} />}
                                    </button>
                                    {/* Filter tabs */}
                                    {showHistory && (
                                        <div className="flex rounded-lg overflow-hidden text-[10px]" style={{ background: 'var(--color-input-bg)' }}>
                                            {(['ALL', 'BUY', 'SELL'] as const).map(f => (
                                                <button key={f} onClick={() => setHistoryFilter(f)}
                                                    className="px-3 py-1.5 font-semibold transition-all"
                                                    style={{
                                                        background: historyFilter === f ? 'var(--color-accent)' : 'transparent',
                                                        color: historyFilter === f ? '#fff' : 'var(--color-text-sub)',
                                                    }}>
                                                    {f === 'ALL' ? 'ทั้งหมด' : f === 'BUY' ? 'ซื้อ' : 'ขาย'}
                                                </button>
                                            ))}
                                        </div>
                                    )}
                                </div>

                                {showHistory && (
                                    <div className="overflow-x-auto">
                                        <table className="w-full">
                                            <thead>
                                                <tr className="text-[10px] border-b" style={{ color: 'var(--color-text-sub)', borderColor: 'var(--color-border)', background: 'var(--color-hover)' }}>
                                                    {['วันที่', 'Symbol', 'ประเภท', 'จำนวน', 'ราคา/หุ้น', 'ค่าคอม', 'มูลค่ารวม', 'หมายเหตุ', ''].map(h => (
                                                        <th key={h} className="text-left px-4 py-2 font-medium whitespace-nowrap">{h}</th>
                                                    ))}
                                                </tr>
                                            </thead>
                                            <tbody>
                                                {txns
                                                    .filter(t => historyFilter === 'ALL' || t.type === historyFilter)
                                                    .map((t) => {
                                                        const isBuy = t.type === 'BUY';
                                                        const cs = CURR_SIGN[t.currency] ?? '฿';
                                                        const total = t.qty * t.price;
                                                        return (
                                                            <tr key={t.id} className="border-b text-xs transition-colors"
                                                                style={{ borderColor: 'var(--color-border)' }}
                                                                onMouseEnter={e => (e.currentTarget.style.background = 'var(--color-hover)')}
                                                                onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}>
                                                                <td className="px-4 py-3 tabular-nums whitespace-nowrap" style={{ color: 'var(--color-text-sub)' }}>{t.date}</td>
                                                                <td className="px-4 py-3 font-semibold whitespace-nowrap" style={{ color: 'var(--color-accent)' }}>
                                                                    {t.symbol}
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
                                                                <td className="px-4 py-3 tabular-nums">{cs}{fmt(t.price)}</td>
                                                                <td className="px-4 py-3 tabular-nums" style={{ color: 'var(--color-text-sub)' }}>{t.fee ? `${cs}${fmt(t.fee)}` : '—'}</td>
                                                                <td className="px-4 py-3 tabular-nums font-medium">{cs}{fmt(total)}</td>
                                                                <td className="px-4 py-3 max-w-[120px] truncate" style={{ color: 'var(--color-text-sub)' }} title={t.note}>{t.note || '—'}</td>
                                                                <td className="px-4 py-3">
                                                                    <button
                                                                        onClick={() => handleDelete(t.id)}
                                                                        disabled={deletingId === t.id}
                                                                        className="p-1.5 rounded-lg transition-colors"
                                                                        style={{ color: 'var(--color-text-sub)' }}
                                                                        onMouseEnter={e => (e.currentTarget.style.color = 'var(--color-red)')}
                                                                        onMouseLeave={e => (e.currentTarget.style.color = 'var(--color-text-sub)')}
                                                                        title="ลบธุรกรรม"
                                                                    >
                                                                        {deletingId === t.id
                                                                            ? <span style={{ display: 'inline-block', width: 12, height: 12, border: '2px solid currentColor', borderTopColor: 'transparent', borderRadius: '50%', animation: 'spin 0.65s linear infinite' }} />
                                                                            : <Trash2 size={12} />}
                                                                    </button>
                                                                </td>
                                                            </tr>
                                                        );
                                                    })}
                                            </tbody>
                                        </table>
                                        {txns.filter(t => historyFilter === 'ALL' || t.type === historyFilter).length === 0 && (
                                            <div className="text-center py-6 text-xs" style={{ color: 'var(--color-text-sub)' }}>
                                                ไม่มีรายการ {historyFilter === 'BUY' ? 'ซื้อ' : 'ขาย'}
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
            {showModal && (
                <div className="glass-overlay fixed inset-0 z-50 flex items-center justify-center" onClick={(e) => e.target === e.currentTarget && setShowModal(false)}>
                    <div className="glass-panel rounded-2xl p-6 w-96 animate-slide-up">
                        <div className="flex items-center justify-between mb-5">
                            <h3 className="font-bold">เพิ่มธุรกรรม</h3>
                            <button onClick={() => setShowModal(false)} style={{ color: 'var(--color-text-sub)' }}><X size={14} /></button>
                        </div>
                        <div className="flex flex-col gap-3">
                            {/* Type Toggle */}
                            <div className="flex rounded-xl overflow-hidden" style={{ background: 'var(--color-input-bg)' }}>
                                {['BUY', 'SELL'].map((t) => (
                                    <button key={t} onClick={() => setForm((f) => ({ ...f, type: t }))}
                                        className="flex-1 py-2 text-xs font-semibold transition-all flex items-center justify-center gap-1.5"
                                        style={{ background: form.type === t ? (t === 'BUY' ? 'var(--color-green)' : 'var(--color-red)') : 'transparent', color: form.type === t ? '#fff' : 'var(--color-text-sub)' }}>
                                        {t === 'BUY' ? <><TrendingUp size={12} /> ซื้อ</> : <><TrendingDown size={12} /> ขาย</>}
                                    </button>
                                ))}
                            </div>

                            {/* Symbol */}
                            <div>
                                <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: 'var(--color-text-sub)' }}>Symbol</div>
                                <input type="text" className="input-field" placeholder="เช่น PTT.BK หรือ AAPL"
                                    value={form.symbol}
                                    onChange={(e) => handleSymbolChange(e.target.value)} />
                            </div>

                            {/* Currency Toggle (auto-detected, แต่เปลี่ยนเองได้) */}
                            <div>
                                <div className="text-[10px] uppercase tracking-wider mb-1.5 flex items-center gap-1.5" style={{ color: 'var(--color-text-sub)' }}>
                                    สกุลเงิน
                                    <span className="text-[9px] px-1.5 py-0.5 rounded" style={{ background: 'var(--color-hover)', color: 'var(--color-text-sub)' }}>
                                        auto-detect จาก symbol
                                    </span>
                                </div>
                                <div className="flex rounded-xl overflow-hidden" style={{ background: 'var(--color-input-bg)' }}>
                                    {['THB', 'USD'].map((c) => (
                                        <button key={c} onClick={() => setForm((f) => ({ ...f, currency: c }))}
                                            className="flex-1 py-2 text-xs font-semibold transition-all"
                                            style={{
                                                background: form.currency === c ? 'var(--color-accent)' : 'transparent',
                                                color: form.currency === c ? '#fff' : 'var(--color-text-sub)',
                                            }}>
                                            {c === 'THB' ? '฿ THB' : '$ USD'}
                                        </button>
                                    ))}
                                </div>
                            </div>

                            {/* จำนวน */}
                            <div>
                                <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: 'var(--color-text-sub)' }}>จำนวน (หุ้น)</div>
                                <input type="number" className="input-field" placeholder="100"
                                    value={form.qty} onChange={(e) => setForm((f) => ({ ...f, qty: e.target.value }))} />
                            </div>

                            {/* ราคาต่อหุ้น พร้อม currency prefix */}
                            <div>
                                <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: 'var(--color-text-sub)' }}>ราคาต่อหุ้น</div>
                                <div className="input-field flex items-center gap-2 p-0 overflow-hidden">
                                    <span className="pl-3 text-xs font-medium shrink-0 select-none" style={{ color: 'var(--color-text-sub)' }}>
                                        {CURR_SIGN[form.currency]}
                                    </span>
                                    <input type="number" className="flex-1 bg-transparent outline-none pr-3 py-2 text-sm" placeholder="38.00"
                                        value={form.price} onChange={(e) => setForm((f) => ({ ...f, price: e.target.value }))} />
                                </div>
                            </div>

                            {/* ค่าคอมมิชชั่น */}
                            <div>
                                <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: 'var(--color-text-sub)' }}>ค่าคอมมิชชั่น</div>
                                <div className="input-field flex items-center gap-2 p-0 overflow-hidden">
                                    <span className="pl-3 text-xs font-medium shrink-0 select-none" style={{ color: 'var(--color-text-sub)' }}>
                                        {CURR_SIGN[form.currency]}
                                    </span>
                                    <input type="number" className="flex-1 bg-transparent outline-none pr-3 py-2 text-sm" placeholder="0"
                                        value={form.fee} onChange={(e) => setForm((f) => ({ ...f, fee: e.target.value }))} />
                                </div>
                            </div>

                            {/* วันที่ */}
                            <div>
                                <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: 'var(--color-text-sub)' }}>วันที่</div>
                                <input type="date" className="input-field"
                                    value={form.date} onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))} />
                            </div>

                            {/* หมายเหตุ */}
                            <div>
                                <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: 'var(--color-text-sub)' }}>หมายเหตุ</div>
                                <input type="text" className="input-field" placeholder="เช่น ซื้อตามแผน DCA"
                                    value={form.note} onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))} />
                            </div>
                            <div className="flex gap-2 mt-2">
                                <button onClick={() => setShowModal(false)} className="btn-outline flex-1 py-2">ยกเลิก</button>
                                <button onClick={handleAdd} disabled={saving} className="btn-accent flex-1 py-2">{saving ? 'กำลังบันทึก…' : 'บันทึก'}</button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
