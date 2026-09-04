import { useState, useEffect, useCallback } from 'react';
import { BellPlus, Timer } from 'lucide-react';
import useAppStore from '@/store/appStore';
import stockService from '@/services/stockService';
import alertService from '@/services/alertService';
import { calculateRSI } from '@/utils/indicators';
import toast from 'react-hot-toast';

function isTimeoutError(err: any): boolean {
    return err?.code === 'ECONNABORTED' || !!err?.message?.includes('timeout');
}

export default function RightPanel({ selectedStock }) {
    const { darkMode } = useAppStore();
    const [fundamentals, setFundamentals] = useState(null);
    const [quote, setQuote] = useState(null);
    const [rsi, setRsi] = useState<number | null>(null);
    const [timedOut, setTimedOut] = useState(false);

    // Fetch quote — single blocking call (backend fetch_quote_now blocks up to 7s server-side).
    // 404 → symbol not found → quote stays null (stockService.getQuote returns {data:null}).
    // Timeout → show retry UI.  No 202 retry loop needed anymore.
    const fetchQuote = useCallback((sym: string, signal: AbortSignal) => {
        stockService.getQuote(sym)
            .then(res => {
                if (signal.aborted) return;
                if (res.data?.price != null) setQuote(res.data);
                // else: not found or no live price — quote stays null, panel shows "—"
            })
            .catch((err) => {
                if (signal.aborted) return;
                if (isTimeoutError(err)) setTimedOut(true);
            });
    }, []);

    const fetchAll = useCallback((sym: string, signal: AbortSignal) => {
        setTimedOut(false);

        stockService.getFundamentals(sym)
            .then(res => { if (!signal.aborted) setFundamentals(res.data); })
            .catch((err) => {
                if (signal.aborted) return;
                if (isTimeoutError(err)) setTimedOut(true);
                setFundamentals(null);
            });

        fetchQuote(sym, signal);

        // Compute real RSI(14) from 1D history bars
        stockService.getHistory(sym, '1D')
            .then(res => {
                if (signal.aborted) return;
                const barsData = res.data.bars ?? [];
                if (barsData.length >= 14) {
                    const rsiData = calculateRSI(barsData, 14);
                    const last = rsiData.at(-1);
                    setRsi(last?.value ?? null);
                }
            })
            .catch((err) => {
                if (signal.aborted) return;
                if (isTimeoutError(err)) setTimedOut(true);
                setRsi(null);
            });
    }, []);

    useEffect(() => {
        if (!selectedStock?.sym) return;
        setFundamentals(null);
        setQuote(null);
        setRsi(null);
        setTimedOut(false);

        // AbortController cancels in-flight fetch if symbol changes before responses arrive
        const controller = new AbortController();
        fetchAll(selectedStock.sym, controller.signal);

        return () => {
            controller.abort();
        };
    }, [selectedStock?.sym, fetchAll]);

    const stats = [
        ['52W High', fundamentals?.week_52_high?.toFixed(2) ?? '—'],
        ['52W Low', fundamentals?.week_52_low?.toFixed(2) ?? '—'],
        ['Avg Vol', fundamentals?.avg_volume ? (fundamentals.avg_volume / 1000000).toFixed(1) + 'M' : '—'],
        ['Beta', fundamentals?.beta?.toFixed(2) ?? '—'],
        ['EPS', fundamentals?.eps?.toFixed(2) ?? '—'],
    ];

    // Only show target if we have a live price — no fake fallback
    const targetPrice = quote?.price ? parseFloat((quote.price * 1.05).toFixed(2)) : null;

    const handleQuickAlert = async () => {
        if (!selectedStock?.sym || targetPrice === null) return;
        try {
            await alertService.create({
                symbol: selectedStock.sym,
                alert_type: 'PRICE_ABOVE',
                condition: 'GREATER_THAN',
                value: targetPrice,
                channel: 'IN_APP'
            });
            toast.success(`Alert set for ${selectedStock.sym} at ${targetPrice}`);
        } catch {
            toast.error('Failed to set alert');
        }
    };

    const rsiPct = rsi != null ? Math.min(Math.max(rsi, 0), 100) : null;
    const rsiColor = rsi == null ? 'var(--color-text-sub)'
        : rsi < 30 ? 'var(--color-green)'
        : rsi > 70 ? 'var(--color-red)'
        : 'var(--color-yellow)';

    return (
        <aside className="panel border-l overflow-y-auto" style={{ width: 220, borderLeftWidth: 1, borderLeftStyle: 'solid', borderColor: 'var(--color-border)' }}>
            {/* Quick Alert */}
            <div className="p-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
                <div className="text-[10px] uppercase tracking-wider mb-2 font-semibold" style={{ color: 'var(--color-text-sub)' }}>Quick Alert</div>
                <div className="flex items-center justify-between p-2 rounded-xl mb-2" style={{ background: 'var(--color-input-bg)' }}>
                    <span className="text-[11px]" style={{ color: 'var(--color-text-sub)' }}>Target (+5%)</span>
                    <span className="text-[11px] font-medium">{targetPrice ?? '—'}</span>
                </div>
                <button
                    onClick={handleQuickAlert}
                    disabled={targetPrice === null}
                    className="btn-accent w-full py-1.5 text-[11px] font-medium rounded-lg disabled:opacity-40 flex items-center justify-center gap-1.5"
                >
                    <BellPlus size={12} />
                    Set Alert
                </button>
            </div>

            {/* Stats */}
            <div className="p-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
                <div className="text-[10px] uppercase tracking-wider mb-2 font-semibold" style={{ color: 'var(--color-text-sub)' }}>Stats</div>
                {timedOut && (
                    <div className="text-[11px] py-1 mb-1 flex items-center gap-1" style={{ color: 'var(--color-text-sub)' }}>
                        <Timer size={12} strokeWidth={2} aria-hidden="true" /> Timed out —{' '}
                        <button
                            className="underline"
                            style={{ color: 'var(--color-accent)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                            onClick={() => {
                                if (!selectedStock?.sym) return;
                                setTimedOut(false);
                                setFundamentals(null);
                                setQuote(null);
                                setRsi(null);
                                const ctrl = new AbortController();
                                fetchAll(selectedStock.sym, ctrl.signal);
                            }}
                        >retry?</button>
                    </div>
                )}
                {stats.map(([k, v]) => (
                    <div key={k} className="flex justify-between items-center py-1.5 border-b last:border-0" style={{ borderColor: 'color-mix(in srgb, var(--color-border) 40%, transparent)' }}>
                        <span className="text-[11px]" style={{ color: 'var(--color-text-sub)' }}>{k}</span>
                        <span className="text-[11px] font-medium tabular-nums">{v}</span>
                    </div>
                ))}
            </div>

            {/* RSI Gauge */}
            <div className="p-3">
                <div className="text-[10px] uppercase tracking-wider mb-2 font-semibold" style={{ color: 'var(--color-text-sub)' }}>RSI (14)</div>
                {rsiPct != null ? (
                    <>
                        <div className="relative my-3">
                            <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'linear-gradient(to right, #34d399, #facc15, #f87171)' }}>
                                <div
                                    className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-white border-2 shadow"
                                    style={{ left: `${rsiPct}%`, borderColor: 'var(--color-accent)', transform: 'translate(-50%, -50%)' }}
                                />
                            </div>
                        </div>
                        <div className="flex justify-between items-center mt-2">
                            <span className="text-[10px] font-medium" style={{ color: 'var(--color-green)' }}>Oversold</span>
                            <span className="text-xs font-bold" style={{ color: rsiColor }}>{rsiPct.toFixed(1)}</span>
                            <span className="text-[10px] font-medium" style={{ color: 'var(--color-red)' }}>Overbought</span>
                        </div>
                    </>
                ) : (
                    <div className="text-[11px] py-4 text-center" style={{ color: 'var(--color-text-sub)' }}>—</div>
                )}
            </div>
        </aside>
    );
}
