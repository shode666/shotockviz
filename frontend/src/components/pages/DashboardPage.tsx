/**
 * Dashboard — personal investment assistant overview
 * Shows: market indices, portfolio summary, movers, near-target alerts
 * Bento Grid layout with semantic design tokens
 */
import { useEffect, useState, useCallback, useRef } from 'react';
import { useNavigate } from '@tanstack/react-router';
import {
    TrendingUp, TrendingDown, RefreshCw, Bell, Briefcase,
    Activity, DollarSign, BarChart2, Zap,
} from 'lucide-react';
import dashboardService from '@/services/dashboardService';
import portfolioService from '@/services/portfolioService';
import useAppStore from '@/store/appStore';
import useAuthStore from '@/store/authStore';
import { SkeletonCard, Skeleton } from '@/components/common/Skeleton';
import { ChangeBadge, MarketStatusBadge } from '@/components/common/Badge';

/* ── tiny helpers ──────────────────────────────────────────────────────── */

function pct(v: number | null | undefined) {
    if (v == null) return '—';
    const sign = v >= 0 ? '+' : '';
    return `${sign}${v.toFixed(2)}%`;
}
function price(v: number | null | undefined, decimals = 2) {
    if (v == null) return '—';
    return v.toLocaleString('th-TH', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
}
function upColor(v: number | null | undefined) {
    if (v == null) return 'var(--color-text-sub)';
    return v >= 0 ? 'var(--color-green)' : 'var(--color-red)';
}

/* ── sub-components ────────────────────────────────────────────────────── */

function IndexCard({ name, symbol, pctVal, priceVal }: {
    name: string; symbol: string;
    pctVal: number | null; priceVal: number | null;
}) {
    const isUSDTHB = symbol === 'THBUSD=X';
    return (
        <div className="panel rounded-2xl p-3.5 border flex flex-col gap-1.5 min-w-0"
            style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
            <div className="flex items-center justify-between gap-2">
                <span className="text-[10px] font-semibold uppercase tracking-wider" style={{ color: 'var(--color-text-sub)' }}>{name}</span>
                {pctVal != null && (
                    <span className="text-[10px] font-bold" style={{ color: upColor(pctVal) }}>
                        {pct(pctVal)}
                    </span>
                )}
            </div>
            <div className="text-lg font-bold tabular-nums">
                {isUSDTHB && priceVal ? `฿${(1 / priceVal).toFixed(2)}` : price(priceVal, isUSDTHB ? 4 : 2)}
            </div>
        </div>
    );
}

function MoverRow({ sym, pctVal, priceVal, onClick }: {
    sym: string; pctVal: number | null; priceVal: number | null; onClick: () => void;
}) {
    return (
        <button
            onClick={onClick}
            className="flex items-center justify-between px-3 py-2 rounded-xl w-full transition-colors hover:bg-[var(--color-hover)] text-left"
        >
            <span className="font-semibold text-xs">{sym}</span>
            <div className="flex flex-col items-end">
                <span className="text-xs font-bold tabular-nums">{price(priceVal)}</span>
                <span className="text-[10px] font-semibold" style={{ color: upColor(pctVal) }}>{pct(pctVal)}</span>
            </div>
        </button>
    );
}

function AlertNearTarget({ symbol, target, current, diffPct, condition }: {
    symbol: string; target: number; current: number; diffPct: number; condition: string;
}) {
    return (
        <div className="flex items-center gap-2 px-3 py-2 rounded-xl border"
            style={{ borderColor: '#f59e0b44', background: 'rgba(245,158,11,0.06)' }}>
            <Bell size={11} className="flex-shrink-0" style={{ color: '#f59e0b' }} />
            <div className="flex-1 min-w-0">
                <span className="font-bold text-xs">{symbol}</span>
                <span className="text-[10px] ml-1.5" style={{ color: 'var(--color-text-sub)' }}>
                    {condition} {target.toFixed(2)} · ปัจจุบัน {current.toFixed(2)}
                </span>
            </div>
            <span className="text-[10px] font-bold" style={{ color: '#f59e0b' }}>±{diffPct.toFixed(1)}%</span>
        </div>
    );
}

/* ── Portfolio equity mini-chart (sparkline via SVG) ────────────────────── */

function SparkLine({ points }: { points: { value: number }[] }) {
    if (!points || points.length < 2) return null;
    const vals = points.map(p => p.value);
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const range = max - min || 1;
    const W = 120, H = 32;
    const coords = points.map((p, i) => {
        const x = (i / (points.length - 1)) * W;
        const y = H - ((p.value - min) / range) * H;
        return `${x},${y}`;
    });
    const pathD = `M${coords.join('L')}`;
    const isUp = vals[vals.length - 1] >= vals[0];
    const color = isUp ? 'var(--color-green)' : 'var(--color-red)';
    return (
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="overflow-visible">
            <polyline points={coords.join(' ')} fill="none" stroke={color} strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        </svg>
    );
}

/* ── Main component ────────────────────────────────────────────────────── */

export default function DashboardPage() {
    const navigate = useNavigate();
    const { setSelectedStock, dataVersion } = useAppStore();
    const { isAuthenticated } = useAuthStore();
    const [data, setData] = useState<any>(null);
    const [perfData, setPerfData] = useState<any>(null);
    const [loading, setLoading] = useState(true);
    const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        try {
            const res = await dashboardService.getOverview();
            setData(res.data);
            setLastUpdated(new Date());

            // Fetch equity curve (6M) for authenticated users
            if (isAuthenticated) {
                try {
                    const perfRes = await portfolioService.getPerformance?.('6M');
                    if (perfRes?.data?.points?.length) setPerfData(perfRes.data);
                } catch { /* not critical */ }
            }
        } catch {
            /* network error */
        } finally {
            setLoading(false);
        }
    }, [isAuthenticated]);

    // Stable ref so the interval never needs to be recreated
    const loadRef = useRef(load);
    useEffect(() => { loadRef.current = load; }, [load]);

    // Interval set up ONCE — never recreated
    useEffect(() => {
        const t = setInterval(() => loadRef.current(), 60_000);
        return () => clearInterval(t);
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    // Immediate load when auth changes OR when backend cache becomes ready
    useEffect(() => {
        loadRef.current();
    }, [load, dataVersion]);

    const goToChart = (symbol: string) => {
        setSelectedStock({ sym: symbol, name: symbol, price: '—', chg: '—', pct: '—', up: true });
        navigate({ to: '/' });
    };

    if (loading && !data) {
        return (
            <div className="flex-1 overflow-auto p-5" style={{ background: 'var(--color-bg)' }}>
                <div className="max-w-7xl mx-auto space-y-5">
                    {/* Header skeleton */}
                    <Skeleton height="32px" width="30%" />

                    {/* Indices skeleton */}
                    <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
                        {[...Array(5)].map((_, i) => (
                            <Skeleton key={i} height="80px" className="rounded-xl" />
                        ))}
                    </div>

                    {/* Bento grid skeleton */}
                    <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">
                        <SkeletonCard className="md:col-span-2" />
                        <SkeletonCard />
                        <SkeletonCard />
                        <SkeletonCard className="xl:col-span-4" />
                    </div>
                </div>
            </div>
        );
    }

    const indices = data?.indices ?? [];
    const portfolio = data?.portfolio;
    const movers = data?.movers ?? [];
    const alertsNear = data?.alerts_near_target ?? [];
    const alertCount = data?.alert_count ?? 0;

    return (
        <div className="flex-1 overflow-auto p-5" style={{ background: 'var(--color-bg)' }}>
            <div className="max-w-7xl mx-auto animate-fade-in space-y-5">

                {/* ── Header ─────────────────────────────────────────────── */}
                <div className="flex items-center justify-between">
                    <div>
                        <h1 className="text-base font-bold flex items-center gap-2">
                            <Activity size={16} style={{ color: 'var(--color-accent)' }} />
                            ภาพรวมตลาด
                        </h1>
                        <p className="text-[10px] mt-0.5" style={{ color: 'var(--color-text-sub)' }}>
                            {lastUpdated ? `อัปเดตล่าสุด ${lastUpdated.toLocaleTimeString('th-TH')}` : 'กำลังโหลด...'}
                        </p>
                    </div>
                    <button
                        onClick={load}
                        disabled={loading}
                        className="p-2 rounded-lg transition-colors hover:bg-[var(--color-hover)]"
                        style={{ color: 'var(--color-text-sub)' }}
                    >
                        <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
                    </button>
                </div>

                {/* ── Market Indices ──────────────────────────────────────── */}
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2.5">
                    {indices.map((idx: any) => (
                        <IndexCard key={idx.name} name={idx.name} symbol={idx.symbol}
                            pctVal={idx.change_pct} priceVal={idx.price} />
                    ))}
                </div>

                {/* ── Bento Grid Main Layout ──────────────────────────────────────── */}
                <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-4 gap-4">

                    {/* ── Portfolio Card (spans 2 cols on XL) ─────────────────────────────────── */}
                    <div className="xl:col-span-2 panel rounded-2xl border p-4 flex flex-col gap-3"
                        style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                        <div className="flex items-center justify-between">
                            <span className="text-[10px] uppercase tracking-wider font-semibold flex items-center gap-1.5" style={{ color: 'var(--color-text-sub)' }}>
                                <Briefcase size={11} /> Portfolio
                            </span>
                            <button onClick={() => navigate({ to: '/portfolio' })}
                                className="text-[10px] font-medium" style={{ color: 'var(--color-accent)' }}>
                                ดูทั้งหมด →
                            </button>
                        </div>

                        {!isAuthenticated ? (
                            <div className="flex-1 flex flex-col items-center justify-center gap-2 py-6">
                                <Briefcase size={24} style={{ color: 'var(--color-text-sub)' }} />
                                <p className="text-xs text-center" style={{ color: 'var(--color-text-sub)' }}>
                                    Login เพื่อดูพอร์ต
                                </p>
                                <button onClick={() => navigate({ to: '/login' })} className="btn-accent text-[10px] px-3 py-1">
                                    เข้าสู่ระบบ
                                </button>
                            </div>
                        ) : portfolio ? (
                            <>
                                <div>
                                    <div className="text-[10px]" style={{ color: 'var(--color-text-sub)' }}>มูลค่าพอร์ต</div>
                                    <div className="text-2xl font-bold tabular-nums mt-0.5">
                                        {price(portfolio.total_value)}
                                    </div>
                                    <div className="flex items-center gap-2 mt-1">
                                        <span className="text-xs font-semibold" style={{ color: upColor(portfolio.unrealized_pl) }}>
                                            {portfolio.unrealized_pl >= 0 ? <TrendingUp size={11} className="inline mr-0.5" /> : <TrendingDown size={11} className="inline mr-0.5" />}
                                            {pct(portfolio.unrealized_pl_pct)}
                                        </span>
                                        <span className="text-[10px]" style={{ color: 'var(--color-text-sub)' }}>
                                            ({price(portfolio.unrealized_pl, 0)})
                                        </span>
                                    </div>
                                </div>

                                {/* Sparkline */}
                                {perfData?.points?.length > 1 && (
                                    <div className="overflow-hidden">
                                        <SparkLine points={perfData.points} />
                                    </div>
                                )}

                                {/* Top holdings */}
                                <div className="space-y-1 mt-1">
                                    {portfolio.top_holdings?.slice(0, 3).map((h: any) => (
                                        <div key={h.symbol} className="flex items-center justify-between text-[11px]">
                                            <button onClick={() => goToChart(h.symbol)}
                                                className="font-semibold hover:text-[var(--color-accent)] transition-colors">
                                                {h.symbol}
                                            </button>
                                            <span style={{ color: upColor(h.unrealized_pct) }}>
                                                {pct(h.unrealized_pct)}
                                            </span>
                                        </div>
                                    ))}
                                </div>
                                <div className="text-[10px]" style={{ color: 'var(--color-text-sub)' }}>
                                    {portfolio.position_count} หลักทรัพย์
                                </div>
                            </>
                        ) : (
                            <div className="flex-1 flex flex-col items-center justify-center gap-2 py-4">
                                <p className="text-xs" style={{ color: 'var(--color-text-sub)' }}>ยังไม่มีพอร์ต</p>
                                <button onClick={() => navigate({ to: '/portfolio' })} className="btn-accent text-[10px] px-3 py-1">
                                    + เพิ่มธุรกรรม
                                </button>
                            </div>
                        )}
                    </div>

                    {/* ── Market Status Card ────────────────────────────────────────────── */}
                    <div className="panel rounded-2xl border p-4 flex flex-col gap-3"
                        style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                        <span className="text-[10px] uppercase tracking-wider font-semibold flex items-center gap-1.5" style={{ color: 'var(--color-text-sub)' }}>
                            <BarChart2 size={11} /> Market Status
                        </span>
                        <div className="flex flex-col gap-3">
                            <div>
                                <div className="text-[10px] mb-1" style={{ color: 'var(--color-text-sub)' }}>SET (Thailand)</div>
                                <MarketStatusBadge isOpen={new Date().getHours() >= 10 && new Date().getHours() < 16} />
                            </div>
                            <div>
                                <div className="text-[10px] mb-1" style={{ color: 'var(--color-text-sub)' }}>US Market</div>
                                <MarketStatusBadge isOpen={new Date().getHours() >= 21 || new Date().getHours() < 4} />
                            </div>
                        </div>
                    </div>

                    {/* ── Top Movers (spans full width on XL) ──────────────────────────────────────────── */}
                    <div className="xl:col-span-4 panel rounded-2xl border p-4 flex flex-col gap-2"
                        style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                        <div className="flex items-center justify-between">
                            <span className="text-[10px] uppercase tracking-wider font-semibold flex items-center gap-1.5" style={{ color: 'var(--color-text-sub)' }}>
                                <TrendingUp size={11} /> Top Movers (Last 24h)
                            </span>
                        </div>
                        <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-2 flex-1">
                            {movers.length === 0 ? (
                                <p className="text-xs text-center py-4 col-span-full" style={{ color: 'var(--color-text-sub)' }}>ไม่มีข้อมูล</p>
                            ) : movers.slice(0, 6).map((m: any) => (
                                <MoverRow key={m.symbol} sym={m.symbol}
                                    pctVal={m.change_pct} priceVal={m.price}
                                    onClick={() => goToChart(m.symbol)} />
                            ))}
                        </div>
                    </div>

                    {/* ── Alerts (moved below for layout) ──────────────────────────────────────────── */}
                    <div className="xl:col-span-4 panel rounded-2xl border p-4 flex flex-col gap-2"
                        style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                        <div className="flex items-center justify-between">
                            <span className="text-[10px] uppercase tracking-wider font-semibold flex items-center gap-1.5" style={{ color: 'var(--color-text-sub)' }}>
                                <Bell size={11} /> Alerts
                            </span>
                            <button onClick={() => navigate({ to: '/alerts' })}
                                className="text-[10px] font-medium" style={{ color: 'var(--color-accent)' }}>
                                จัดการ →
                            </button>
                        </div>

                        {!isAuthenticated ? (
                            <p className="text-xs py-4 text-center" style={{ color: 'var(--color-text-sub)' }}>Login เพื่อดู Alert</p>
                        ) : (
                            <>
                                <div className="flex items-center gap-2">
                                    <Zap size={16} style={{ color: 'var(--color-accent)' }} />
                                    <span className="text-lg font-bold">{alertCount}</span>
                                    <span className="text-[10px]" style={{ color: 'var(--color-text-sub)' }}>active alerts</span>
                                </div>

                                {alertsNear.length > 0 ? (
                                    <div className="space-y-1.5 mt-1">
                                        <p className="text-[10px] font-semibold" style={{ color: '#f59e0b' }}>
                                            ⚡ ใกล้ถึง target:
                                        </p>
                                        {alertsNear.map((a: any, i: number) => (
                                            <AlertNearTarget key={i} symbol={a.symbol} target={a.target}
                                                current={a.current} diffPct={a.diff_pct} condition={a.condition} />
                                        ))}
                                    </div>
                                ) : alertCount > 0 ? (
                                    <p className="text-[10px]" style={{ color: 'var(--color-text-sub)' }}>
                                        ราคายังห่าง target ทุก alert
                                    </p>
                                ) : (
                                    <div className="flex flex-col items-center gap-2 py-4">
                                        <Bell size={20} style={{ color: 'var(--color-text-sub)' }} />
                                        <p className="text-xs" style={{ color: 'var(--color-text-sub)' }}>ยังไม่มี Alert</p>
                                        <button onClick={() => navigate({ to: '/alerts' })} className="btn-accent text-[10px] px-3 py-1">
                                            + สร้าง Alert
                                        </button>
                                    </div>
                                )}
                            </>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
