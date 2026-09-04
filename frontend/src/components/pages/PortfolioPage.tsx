import { useState, useMemo } from 'react';
import toast from 'react-hot-toast';
import { Briefcase, Trash2, History, BarChart2, FilterX, Timer } from 'lucide-react';
import portfolioService from '@/services/portfolioService';
import useAuthStore from '@/store/authStore';
import { displaySymbol, formatPriceTH } from '@/utils/formatters';
import { AddTransactionModal } from '@/components/portfolio/AddTransactionModal';
import { HoldingsTable } from '@/components/portfolio/HoldingsTable';
import { usePortfolioData } from '@/hooks/usePortfolioData';

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
    const { analytics, txns, loading, timedOut, reload } = usePortfolioData();
    const [showModal, setShowModal] = useState(false);
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
            const msg = err?.response?.data?.detail || err?.message || 'ลบธุรกรรมไม่สำเร็จ';
            toast.error(msg);
            console.error('[Portfolio] Delete failed:', err);
        } finally { setDeletingId(null); }
    };

    const fmtQty = (n) => n != null ? parseFloat(n.toFixed(8)).toString() : '—';
    const pnlUp = analytics ? analytics.unrealized_pl >= 0 : true;

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
                        <Timer size={24} strokeWidth={2} className="mb-3 mx-auto" aria-hidden="true" style={{ color: 'var(--color-text-sub)' }} />
                        <p className="text-sm font-medium mb-1">Request timed out</p>
                        <p className="text-xs mb-4" style={{ color: 'var(--color-text-sub)' }}>ข้อมูลใช้เวลานานเกินไป — กรุณาลองใหม่</p>
                        <button onClick={reload} className="btn-accent">Retry</button>
                    </div>
                ) : (
                    <>
                        {/* Stats */}
                        <div className="grid grid-cols-2 md:grid-cols-4 gap-4 mb-5">
                            <StatCard label="มูลค่ารวม" value={`฿${formatPriceTH(analytics?.total_value)}`} />
                            <StatCard label="ต้นทุนรวม" value={`฿${formatPriceTH(analytics?.total_cost)}`} />
                            <StatCard
                                label="กำไร/ขาดทุน"
                                value={`${pnlUp ? '+' : '-'}฿${formatPriceTH(analytics?.unrealized_pl != null ? Math.abs(analytics.unrealized_pl) : null)}`}
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
                                style={{ color: activeTab === 'holdings' ? 'var(--color-accent)' : 'var(--color-text-sub)' }}
                            >
                                <BarChart2 size={13} />
                                Holdings
                                {analytics?.holdings?.length > 0 && (
                                    <span className="ml-1 text-[9px] px-1.5 py-0.5 rounded-full" style={{ background: activeTab === 'holdings' ? 'var(--color-accent)' : 'var(--color-hover)', color: activeTab === 'holdings' ? '#fff' : 'var(--color-text-sub)' }}>
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
                                style={{ color: activeTab === 'history' ? 'var(--color-accent)' : 'var(--color-text-sub)' }}
                            >
                                <History size={13} />
                                ประวัติธุรกรรม
                                {txns.length > 0 && (
                                    <span className="ml-1 text-[9px] px-1.5 py-0.5 rounded-full" style={{ background: activeTab === 'history' ? 'var(--color-accent)' : 'var(--color-hover)', color: activeTab === 'history' ? '#fff' : 'var(--color-text-sub)' }}>
                                        {txns.length}
                                    </span>
                                )}
                                {activeTab === 'history' && (
                                    <span className="absolute bottom-0 left-0 right-0 h-0.5 rounded-t-full" style={{ background: 'var(--color-accent)' }} />
                                )}
                            </button>
                        </div>

                        {/* Tab: Holdings */}
                        {activeTab === 'holdings' && (
                            <HoldingsTable holdings={analytics?.holdings ?? []} hasPendingPrices={analytics?.has_pending_prices ?? false} />
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
                                                    background: historyFilter === f ? 'var(--color-accent)' : 'transparent',
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
                                            background: filterSymbol ? 'var(--color-accent)' : 'var(--color-input-bg)',
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
                                            background: filterMonth ? 'var(--color-accent)' : 'var(--color-input-bg)',
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
                                        <button onClick={() => setShowModal(true)} className="btn-accent">+ เพิ่มธุรกรรม</button>
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
                                                            <td className="px-4 py-3 font-semibold whitespace-nowrap" style={{ color: 'var(--color-accent)' }}>
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
            <AddTransactionModal isOpen={showModal} onClose={() => setShowModal(false)} onSuccess={reload} />
        </div>
    );
}
