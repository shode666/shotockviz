import { TrendingUp, TrendingDown, Activity } from 'lucide-react';
import { displaySymbol } from '@/utils/formatters';

interface MoverRowProps {
    sym: string;
    pctVal: number | null;
    priceVal: number | null;
    onClick: () => void;
}

const fmtPct = (v: number | null | undefined) => {
    if (v == null) return null;
    const sign = v >= 0 ? '+' : '';
    return `${sign}${v.toFixed(2)}%`;
};

const fmtPrice = (v: number | null | undefined, decimals = 2) => {
    if (v == null) return '—';
    return v.toLocaleString('th-TH', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
};

const upColor = (v: number | null | undefined) => {
    if (v == null) return 'var(--color-text-sub)';
    return v >= 0 ? 'var(--color-green)' : 'var(--color-red)';
};

function MoverRow({ sym, pctVal, priceVal, onClick }: MoverRowProps) {
    const p = fmtPct(pctVal);
    const isUp = pctVal != null ? pctVal >= 0 : null;
    const hasData = priceVal != null;

    return (
        <button
            onClick={onClick}
            className="flex items-center justify-between px-3 py-2.5 rounded-xl w-full transition-colors hover:bg-[var(--color-hover)] text-left gap-3"
        >
            <div className="flex items-center gap-2 min-w-0">
                <span
                    className="shrink-0 w-5 h-5 rounded-md flex items-center justify-center"
                    style={{
                        background:
                            isUp === null
                                ? 'rgba(148,163,184,0.10)'
                                : isUp
                                  ? 'rgba(52,211,153,0.12)'
                                  : 'rgba(248,113,113,0.12)',
                    }}
                >
                    {isUp === null ? (
                        <Activity size={11} style={{ color: 'var(--color-text-sub)', opacity: 0.5 }} />
                    ) : isUp ? (
                        <TrendingUp size={11} style={{ color: 'var(--color-green)' }} />
                    ) : (
                        <TrendingDown size={11} style={{ color: 'var(--color-red)' }} />
                    )}
                </span>
                <span className="font-bold text-xs truncate">{displaySymbol(sym)}</span>
            </div>
            <div className="flex items-center gap-3 shrink-0">
                {hasData ? (
                    <>
                        <span className="text-xs font-bold tabular-nums">{fmtPrice(priceVal)}</span>
                        {p && (
                            <span
                                className="text-[10px] font-semibold tabular-nums min-w-[52px] text-right"
                                style={{ color: upColor(pctVal) }}
                            >
                                {p}
                            </span>
                        )}
                    </>
                ) : (
                    <span className="text-[10px] tabular-nums" style={{ color: 'var(--color-text-sub)' }}>
                        รอข้อมูล…
                    </span>
                )}
            </div>
        </button>
    );
}

interface TopMoversProps {
    movers: Array<{
        symbol: string;
        change_pct: number | null;
        price: number | null;
    }>;
    onSymbolClick: (symbol: string) => void;
}

export function TopMovers({ movers, onSymbolClick }: TopMoversProps) {
    // Sort movers: put ones with actual data first
    const sortedMovers = [...movers].sort((a, b) => {
        const aHas = a.price != null ? 1 : 0;
        const bHas = b.price != null ? 1 : 0;
        return bHas - aHas || Math.abs(b.change_pct ?? 0) - Math.abs(a.change_pct ?? 0);
    });

    return (
        <div
            className="md:col-span-3 xl:col-span-2 panel rounded-xl border p-4 flex flex-col gap-2"
            style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}
        >
            <span
                className="text-[10px] uppercase tracking-wider font-semibold flex items-center gap-1.5"
                style={{ color: 'var(--color-text-sub)' }}
            >
                <TrendingUp size={11} /> Top Movers (Watchlist 24h)
            </span>
            {sortedMovers.length === 0 ? (
                <p className="text-xs text-center py-4" style={{ color: 'var(--color-text-sub)' }}>
                    ไม่มีข้อมูล
                </p>
            ) : (
                // Single column per mock (page-dashboard.html .mover rows) — the card
                // is now only 2 of 4 bento columns wide, so a multi-col grid here
                // truncated symbols like KBANK/AAPL down to one letter (Uma g2 #3)
                <div className="grid grid-cols-1 gap-0.5">
                    {sortedMovers.map((m: any) => (
                        <MoverRow
                            key={m.symbol}
                            sym={m.symbol}
                            pctVal={m.change_pct}
                            priceVal={m.price}
                            onClick={() => onSymbolClick(m.symbol)}
                        />
                    ))}
                </div>
            )}
        </div>
    );
}
