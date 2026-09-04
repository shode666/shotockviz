/**
 * Dashboard — personal investment assistant overview
 * Shows: market indices, portfolio summary, movers, near-target alerts
 * Bento Grid layout with semantic design tokens
 */
import { useEffect, useState, useCallback, useRef } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { TrendingUp, TrendingDown, RefreshCw, Briefcase, Activity, BarChart2, ArrowRight } from 'lucide-react';
import dashboardService from '@/services/dashboardService';
import portfolioService from '@/services/portfolioService';
import useAppStore from '@/store/appStore';
import useAuthStore from '@/store/authStore';
import { MarketStatusBadge } from '@/components/common/Badge';
import { IndexCards } from '@/components/dashboard/IndexCards';
import { TopMovers } from '@/components/dashboard/TopMovers';
import { AlertsNearTarget } from '@/components/dashboard/AlertsNearTarget';
import { LoadingState } from '@/components/ui/LoadingState';
import { ErrorState } from '@/components/ui/ErrorState';
import { formatPrice, formatPct, upColor, displaySymbol } from '@/utils/formatters';

/* ── SparkLine ─────────────────────────────────────────────────────────── */

function SparkLine({ points }: { points: { value: number }[] }) {
    if (!points || points.length < 2) return null;
    const vals = points.map(p => p.value);
    const min = Math.min(...vals);
    const max = Math.max(...vals);
    const range = max - min || 1;
    const W = 100, H = 28;
    const coords = points.map((p, i) => {
        const x = (i / (points.length - 1)) * W;
        const y = H - ((p.value - min) / range) * (H - 2) - 1;
        return `${x},${y}`;
    });
    const isUp = vals[vals.length - 1] >= vals[0];
    const color = isUp ? 'var(--color-green)' : 'var(--color-red)';
    return (
        <svg width={W} height={H} viewBox={`0 0 ${W} ${H}`} className="overflow-visible opacity-70">
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
    const [error, setError] = useState<string | null>(null);
    const [lastUpdated, setLastUpdated] = useState<Date | null>(null);

    const load = useCallback(async () => {
        setLoading(true);
        setError(null);
        try {
            const res = await dashboardService.getOverview();
            setData(res.data);
            setLastUpdated(new Date());

            if (isAuthenticated) {
                try {
                    const perfRes = await portfolioService.getPerformance?.('6M');
                    if (perfRes?.data?.points?.length) setPerfData(perfRes.data);
                } catch { /* not critical */ }
            }
        } catch (err: any) {
            // Capture error message for retry UI
            setError(err?.message || 'เกิดข้อผิดพลาดในการโหลด Dashboard');
            setData(null);
        } finally {
            setLoading(false);
        }
    }, [isAuthenticated]);

    const loadRef = useRef(load);
    useEffect(() => { loadRef.current = load; }, [load]);
    useEffect(() => {
        const t = setInterval(() => loadRef.current(), 60_000);
        return () => clearInterval(t);
    }, []); // eslint-disable-line react-hooks/exhaustive-deps
    useEffect(() => { loadRef.current(); }, [load, dataVersion]);

    const goToChart = (symbol: string) => {
        setSelectedStock({ sym: symbol, name: symbol, price: '—', chg: '—', pct: '—', up: true });
        navigate({ to: '/' });
    };

    if (error && !data) {
        return <ErrorState title="ไม่สามารถโหลด Dashboard" message={error} onRetry={load} isLoading={loading} />;
    }

    if (loading && !data) {
        return <LoadingState variant="dashboard" />;
    }

    const indices = data?.indices ?? [];
    const portfolio = data?.portfolio;
    const movers = data?.movers ?? [];
    const alertsNear = data?.alerts_near_target ?? [];
    const alertCount = data?.alert_count ?? 0;

    // Sort movers: put ones with actual data first
    const sortedMovers = [...movers].sort((a, b) => {
        const aHas = a.price != null ? 1 : 0;
        const bHas = b.price != null ? 1 : 0;
        return bHas - aHas || Math.abs(b.change_pct ?? 0) - Math.abs(a.change_pct ?? 0);
    });

    return (
        <div className="flex-1 overflow-auto p-5" style={{ background: 'var(--color-bg)' }}>
            <div className="max-w-7xl mx-auto animate-fade-in space-y-4">

                {/* ── Header ─────────────────────────────────────────────── */}
                <div className="flex items-center justify-between">
                    <div>
                        <h1 className="text-sm font-bold flex items-center gap-2">
                            <Activity size={15} style={{ color: 'var(--color-accent)' }} />
                            ภาพรวมตลาด
                        </h1>
                        <p className="text-[10px] mt-0.5" style={{ color: 'var(--color-text-sub)' }}>
                            {lastUpdated ? `อัปเดตล่าสุด ${lastUpdated.toLocaleTimeString('th-TH')}` : 'กำลังโหลด...'}
                        </p>
                    </div>
                    <button
                        onClick={load}
                        disabled={loading}
                        aria-label="รีเฟรชข้อมูล"
                        className="p-1.5 rounded-lg transition-colors hover:bg-[var(--color-hover)]"
                        style={{ color: 'var(--color-text-sub)' }}
                    >
                        <RefreshCw size={13} className={loading ? 'animate-spin' : ''} aria-hidden="true" />
                    </button>
                </div>

                {/* ── Market Indices ──────────────────────────────────────── */}
                <IndexCards indices={indices} />

                {/* ── Bento Main Grid ─────────────────────────────────────── */}
                <div className="grid grid-cols-1 md:grid-cols-3 xl:grid-cols-4 gap-4">

                    {/* ── Portfolio (2 cols) ────────────────────────────────── */}
                    <div className="md:col-span-2 panel rounded-xl border p-4 flex flex-col gap-3"
                        style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                        <div className="flex items-center justify-between">
                            <span className="text-[10px] uppercase tracking-wider font-semibold flex items-center gap-1.5"
                                style={{ color: 'var(--color-text-sub)' }}>
                                <Briefcase size={11} /> Portfolio
                            </span>
                            <button onClick={() => navigate({ to: '/portfolio' })}
                                className="text-[10px] font-medium transition-colors hover:opacity-70 flex items-center gap-0.5"
                                style={{ color: 'var(--color-accent-text)' }}>
                                ดูทั้งหมด <ArrowRight size={12} strokeWidth={2} aria-hidden="true" />
                            </button>
                        </div>

                        {!isAuthenticated ? (
                            <div className="flex-1 flex flex-col items-center justify-center gap-2 py-5">
                                <Briefcase size={22} style={{ color: 'var(--color-text-sub)' }} />
                                <p className="text-xs text-center" style={{ color: 'var(--color-text-sub)' }}>Login เพื่อดูพอร์ต</p>
                                <button onClick={() => navigate({ to: '/login' })} className="btn-accent text-[10px] px-3 py-1 mt-1">
                                    เข้าสู่ระบบ
                                </button>
                            </div>
                        ) : portfolio ? (
                            <div className="flex gap-4">
                                {/* Left: value + PnL */}
                                <div className="flex-1 min-w-0">
                                    <div className="text-[10px] mb-0.5" style={{ color: 'var(--color-text-sub)' }}>มูลค่าพอร์ต</div>
                                    <div className="text-2xl font-bold tabular-nums leading-tight">
                                        {formatPrice(portfolio.total_value)}
                                    </div>
                                    <div className="flex items-center gap-2 mt-1.5">
                                        <span className="text-xs font-bold" style={{ color: upColor(portfolio.unrealized_pl) }}>
                                            {portfolio.unrealized_pl >= 0 ? <TrendingUp size={11} className="inline mr-0.5" /> : <TrendingDown size={11} className="inline mr-0.5" />}
                                            {formatPct(portfolio.unrealized_pl_pct)}
                                        </span>
                                        <span className="text-[10px]" style={{ color: 'var(--color-text-sub)' }}>
                                            ({portfolio.unrealized_pl >= 0 ? '+' : '-'}{formatPrice(Math.abs(portfolio.unrealized_pl), 0)})
                                        </span>
                                    </div>
                                    <div className="text-[10px] mt-3" style={{ color: 'var(--color-text-sub)' }}>
                                        {portfolio.position_count} หลักทรัพย์
                                    </div>
                                    {/* Sparkline */}
                                    {perfData?.points?.length > 1 && (
                                        <div className="mt-2">
                                            <SparkLine points={perfData.points} />
                                        </div>
                                    )}
                                </div>
                                {/* Right: top holdings */}
                                {portfolio.top_holdings?.length > 0 && (
                                    <div className="flex flex-col gap-1.5 shrink-0 min-w-[110px]">
                                        <div className="text-[10px] font-semibold mb-0.5" style={{ color: 'var(--color-text-sub)' }}>Top Holdings</div>
                                        {portfolio.top_holdings.slice(0, 4).map((h: any) => (
                                            <div key={h.symbol} className="flex items-center justify-between gap-2">
                                                <button onClick={() => goToChart(h.symbol)}
                                                    className="font-bold text-[11px] hover:opacity-70 transition-opacity truncate"
                                                    style={{ color: 'var(--color-accent-text)' }}>
                                                    {displaySymbol(h.symbol)}
                                                </button>
                                                <span className="text-[10px] font-semibold tabular-nums shrink-0"
                                                    style={{ color: upColor(h.unrealized_pct) }}>
                                                    {formatPct(h.unrealized_pct) ?? '—'}
                                                </span>
                                            </div>
                                        ))}
                                    </div>
                                )}
                            </div>
                        ) : (
                            <div className="flex-1 flex flex-col items-center justify-center gap-2 py-5">
                                <p className="text-xs" style={{ color: 'var(--color-text-sub)' }}>ยังไม่มีพอร์ต</p>
                                <button onClick={() => navigate({ to: '/portfolio' })} className="btn-accent text-[10px] px-3 py-1">
                                    + เพิ่มธุรกรรม
                                </button>
                            </div>
                        )}
                    </div>

                    {/* ── Market Status ─────────────────────────────────────── */}
                    <div className="xl:col-span-2 panel rounded-xl border p-4 flex flex-col gap-3"
                        style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                        <span className="text-[10px] uppercase tracking-wider font-semibold flex items-center gap-1.5"
                            style={{ color: 'var(--color-text-sub)' }}>
                            <BarChart2 size={11} /> Market Status
                        </span>
                        <div className="grid grid-cols-2 gap-4">
                            <div>
                                <div className="text-[10px] mb-1" style={{ color: 'var(--color-text-sub)' }}>SET (Thailand)</div>
                                <MarketStatusBadge isOpen={new Date().getHours() >= 10 && new Date().getHours() < 16} />
                                <div className="text-[10px] mt-1" style={{ color: 'var(--color-text-sub)' }}>10:00 – 16:30 ICT</div>
                            </div>
                            <div>
                                <div className="text-[10px] mb-1" style={{ color: 'var(--color-text-sub)' }}>US Market</div>
                                <MarketStatusBadge isOpen={new Date().getHours() >= 21 || new Date().getHours() < 4} />
                                <div className="text-[10px] mt-1" style={{ color: 'var(--color-text-sub)' }}>21:30 – 04:00 ICT</div>
                            </div>
                        </div>
                    </div>

                    {/* ── Top Movers ──────────────────────────────────────────── */}
                    <TopMovers movers={sortedMovers} onSymbolClick={goToChart} />

                    {/* ── Alerts ──────────────────────────────────────────────── */}
                    <AlertsNearTarget
                        isAuthenticated={isAuthenticated}
                        alertCount={alertCount}
                        alertsNear={alertsNear}
                        onNavigateToAlerts={() => navigate({ to: '/alerts' })}
                        onNavigateToLogin={() => navigate({ to: '/login' })}
                    />
                </div>
            </div>
        </div>
    );
}
