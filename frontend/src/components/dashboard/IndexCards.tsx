import { ArrowUpRight, ArrowDownRight } from 'lucide-react';

interface IndexCardProps {
    name: string;
    symbol: string;
    pctVal: number | null;
    priceVal: number | null;
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

function IndexCard({ name, symbol, pctVal, priceVal }: IndexCardProps) {
    const isUSDTHB = symbol === 'THBUSD=X';
    const displayPrice = isUSDTHB && priceVal ? `฿${(1 / priceVal).toFixed(2)}` : fmtPrice(priceVal, isUSDTHB ? 4 : 2);
    const p = fmtPct(pctVal);
    const isUp = pctVal != null ? pctVal >= 0 : null;

    return (
        <div
            className="panel rounded-xl p-3 border flex flex-col gap-1 min-w-0"
            style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}
        >
            <div className="flex items-center justify-between gap-1">
                <span className="text-[10px] font-semibold uppercase tracking-wider truncate" style={{ color: 'var(--color-text-sub)' }}>
                    {name}
                </span>
                {isUp !== null && (
                    <span className="shrink-0" style={{ color: upColor(pctVal) }}>
                        {isUp ? <ArrowUpRight size={12} /> : <ArrowDownRight size={12} />}
                    </span>
                )}
            </div>
            <div className="text-base font-bold tabular-nums leading-tight">{displayPrice}</div>
            {p != null ? (
                <div className="text-[11px] font-semibold tabular-nums" style={{ color: upColor(pctVal) }}>
                    {p}
                </div>
            ) : (
                <div className="text-[11px]" style={{ color: 'var(--color-text-sub)' }}>
                    —
                </div>
            )}
        </div>
    );
}

interface IndexCardsProps {
    indices: Array<{
        name: string;
        symbol: string;
        change_pct: number | null;
        price: number | null;
    }>;
}

export function IndexCards({ indices }: IndexCardsProps) {
    return (
        <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-2.5">
            {indices.map((idx: any) => (
                <IndexCard
                    key={idx.name}
                    name={idx.name}
                    symbol={idx.symbol}
                    pctVal={idx.change_pct}
                    priceVal={idx.price}
                />
            ))}
        </div>
    );
}
