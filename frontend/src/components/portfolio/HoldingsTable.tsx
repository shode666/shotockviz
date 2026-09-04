import { Briefcase } from 'lucide-react';
import { displaySymbol } from '@/utils/formatters';

interface Holding {
    symbol: string;
    qty: number;
    avg_cost: number;
    current_price: number | null;
    current_value: number | null;
    unrealized_pl: number | null;
    unrealized_pl_pct: number | null;
    currency?: string;
}

interface HoldingsTableProps {
    holdings: Holding[];
    hasPendingPrices: boolean;
}

const CURR_SIGN: Record<string, string> = { THB: '฿', USD: '$' };

const fmt = (n: number | null | undefined, decimals = 2) =>
    n != null ? n.toLocaleString('th-TH', { minimumFractionDigits: decimals, maximumFractionDigits: decimals }) : '—';

export function HoldingsTable({ holdings, hasPendingPrices }: HoldingsTableProps) {
    if (!holdings || holdings.length === 0) {
        return (
            <div className="panel border rounded-2xl p-8 text-center" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                <div className="mb-3 flex justify-center">
                    <Briefcase size={32} style={{ color: 'var(--color-text-sub)' }} />
                </div>
                <p className="text-sm font-medium mb-1">ยังไม่มีหุ้นในพอร์ต</p>
                <p className="text-xs mb-4" style={{ color: 'var(--color-text-sub)' }}>
                    เพิ่มธุรกรรมซื้อ/ขายเพื่อเริ่มติดตามพอร์ต
                </p>
            </div>
        );
    }

    return (
        <div className="panel border rounded-2xl overflow-hidden" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
            <table className="w-full">
                <thead>
                    <tr
                        className="text-[10px] border-b"
                        style={{ color: 'var(--color-text-sub)', borderColor: 'var(--color-border)', background: 'var(--color-hover)' }}
                    >
                        {['Symbol', 'จำนวน', 'ต้นทุนเฉลี่ย', 'ราคาปัจจุบัน', 'มูลค่า', 'กำไร/ขาดทุน', '%'].map((h) => (
                            <th key={h} className="text-left px-4 py-2 font-medium">
                                {h}
                            </th>
                        ))}
                    </tr>
                </thead>
                <tbody>
                    {holdings.map((h) => {
                        const up = (h.unrealized_pl ?? 0) >= 0;
                        const cs = CURR_SIGN[h.currency ?? 'THB'] ?? '฿';
                        return (
                            <tr
                                key={h.symbol}
                                className="border-b text-xs transition-colors"
                                style={{ borderColor: 'var(--color-border)' }}
                                onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-hover)')}
                                onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                            >
                                <td className="px-4 py-3 font-semibold" style={{ color: 'var(--color-accent-text)' }}>
                                    {displaySymbol(h.symbol)}
                                    <span
                                        className="ml-1.5 text-[9px] px-1 py-0.5 rounded font-normal"
                                        style={{ background: 'var(--color-hover)', color: 'var(--color-text-sub)' }}
                                    >
                                        {h.currency ?? 'THB'}
                                    </span>
                                </td>
                                <td className="px-4 py-3 tabular-nums">{h.qty.toLocaleString()}</td>
                                <td className="px-4 py-3 tabular-nums">
                                    {cs}
                                    {fmt(h.avg_cost)}
                                </td>
                                <td className="px-4 py-3 tabular-nums">
                                    {h.current_price != null ? (
                                        <>
                                            {cs}
                                            {fmt(h.current_price)}
                                        </>
                                    ) : hasPendingPrices ? (
                                        <span className="text-[10px]" style={{ color: 'var(--color-text-sub)' }}>
                                            รอข้อมูล...
                                        </span>
                                    ) : (
                                        <span className="text-[10px]" style={{ color: 'var(--color-yellow)' }}>
                                            ไม่มีข้อมูล
                                        </span>
                                    )}
                                </td>
                                <td className="px-4 py-3 tabular-nums">
                                    {h.current_value != null ? (
                                        <>
                                            {cs}
                                            {fmt(h.current_value)}
                                        </>
                                    ) : (
                                        '—'
                                    )}
                                </td>
                                <td
                                    className="px-4 py-3 tabular-nums font-medium"
                                    style={{ color: up ? 'var(--color-green)' : 'var(--color-red)' }}
                                >
                                    {h.unrealized_pl != null ? (
                                        <>
                                            {up ? '+' : '-'}
                                            {cs}
                                            {fmt(Math.abs(h.unrealized_pl))}
                                        </>
                                    ) : (
                                        '—'
                                    )}
                                </td>
                                <td
                                    className="px-4 py-3 tabular-nums"
                                    style={{ color: up ? 'var(--color-green)' : 'var(--color-red)' }}
                                >
                                    {h.unrealized_pl_pct != null ? (
                                        <>
                                            {up ? '+' : ''}
                                            {fmt(h.unrealized_pl_pct)}%
                                        </>
                                    ) : (
                                        '—'
                                    )}
                                </td>
                            </tr>
                        );
                    })}
                </tbody>
            </table>
        </div>
    );
}
