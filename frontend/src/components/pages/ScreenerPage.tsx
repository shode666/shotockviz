import { useState } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { SlidersHorizontal, Save, Play, Loader2, Download } from 'lucide-react';
import useAppStore from '@/store/appStore';
import stockService from '@/services/stockService';

const FILTER_OPTIONS = {
    market: ['SET + US', 'SET', 'US'],
    rsi: ['< 30 (Oversold)', '30–70 (Neutral)', '> 70 (Overbought)', 'Any'],
    volume: ['> 2x Average', '> 1.5x Average', 'Any'],
    macd: ['Buy Signal', 'Sell Signal', 'Any'],
    price: ['> MA200', '> MA50', '< MA200', 'Any'],
};

// Map UI labels → API param values
const FILTER_MAP = {
    market: { 'SET + US': 'all', 'SET': 'SET', 'US': 'US' },
    rsi: { '< 30 (Oversold)': 'oversold', '30–70 (Neutral)': 'neutral', '> 70 (Overbought)': 'overbought', 'Any': 'any' },
    volume: { '> 2x Average': '2x', '> 1.5x Average': '1.5x', 'Any': 'any' },
    macd: { 'Buy Signal': 'buy', 'Sell Signal': 'sell', 'Any': 'any' },
    price: { '> MA200': 'above_ma200', '> MA50': 'above_ma50', '< MA200': 'below_ma200', 'Any': 'any' },
};

const SIGNAL_STYLE = {
    'Strong Buy': { bg: 'rgba(52,211,153,0.15)', color: 'var(--color-green)' },
    'Buy': { bg: 'rgba(96,165,250,0.15)', color: 'var(--color-blue)' },
    'Neutral': { bg: 'rgba(107,112,132,0.15)', color: 'var(--color-text-sub)' },
    'Sell': { bg: 'rgba(251,113,133,0.15)', color: 'var(--color-red)' },
};

export default function ScreenerPage() {
    const { setSelectedStock } = useAppStore();
    const navigate = useNavigate();
    const [filters, setFilters] = useState({
        market: 'SET + US',
        rsi: '< 30 (Oversold)',
        volume: '> 2x Average',
        macd: 'Buy Signal',
        price: '> MA200',
    });
    const [results, setResults] = useState([]);
    const [loading, setLoading] = useState(false);
    const [hasRun, setHasRun] = useState(false);
    const [error, setError] = useState('');

    const handleRunScreen = async () => {
        setLoading(true);
        setHasRun(true);
        setError('');
        const params = {
            market: FILTER_MAP.market[filters.market] ?? 'all',
            rsi: FILTER_MAP.rsi[filters.rsi] ?? 'any',
            volume: FILTER_MAP.volume[filters.volume] ?? 'any',
            macd: FILTER_MAP.macd[filters.macd] ?? 'any',
            price: FILTER_MAP.price[filters.price] ?? 'any',
        };
        try {
            const { data } = await stockService.screener(params);
            setResults(data);
        } catch (e) {
            setError('เกิดข้อผิดพลาดในการดึงข้อมูล ลองใหม่อีกครั้ง');
            setResults([]);
        } finally {
            setLoading(false);
        }
    };

    const handleRowClick = (r) => {
        setSelectedStock({ sym: r.sym, name: r.name, price: r.price, chg: r.chg, pct: r.chg, up: r.up });
        navigate({ to: '/' });
    };

    return (
        <div className="flex-1 overflow-auto p-6" style={{ background: 'var(--color-bg)' }}>
            <div className="max-w-5xl mx-auto animate-fade-in">

                {/* Header */}
                <div className="flex items-center justify-between mb-5">
                    <div>
                        <h2 className="text-base font-bold flex items-center gap-2">
                            <SlidersHorizontal size={16} />
                            Stock Screener
                        </h2>
                        <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-sub)' }}>กรองหุ้นด้วยเงื่อนไขที่ต้องการ</p>
                    </div>
                    <div className="flex gap-2">
                        <button className="btn-outline flex items-center gap-1.5">
                            <Save size={12} />
                            Save Filter
                        </button>
                        <button className="btn-accent flex items-center gap-1.5" onClick={handleRunScreen} disabled={loading}>
                            {loading
                                ? <><Loader2 size={12} className="animate-spin" /> กำลังค้นหา…</>
                                : <><Play size={12} /> Run Screen</>}
                        </button>
                    </div>
                </div>

                {/* Filter grid */}
                <div className="panel border rounded-2xl p-4 mb-4" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                    <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                        {Object.entries(filters).map(([key, val]) => (
                            <div key={key}>
                                <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: 'var(--color-text-sub)' }}>{key}</div>
                                <select
                                    className="input-field text-[11px] py-1.5 glass-select"
                                    value={val}
                                    onChange={(e) => setFilters((f) => ({ ...f, [key]: e.target.value }))}
                                    style={{ cursor: 'pointer' }}
                                >
                                    {(FILTER_OPTIONS[key] || [val]).map((o) => (
                                        <option key={o}>{o}</option>
                                    ))}
                                </select>
                            </div>
                        ))}
                    </div>
                </div>

                {/* Results table */}
                <div className="panel border rounded-2xl overflow-hidden" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                    <div className="px-4 py-3 border-b flex items-center justify-between" style={{ borderColor: 'var(--color-border)' }}>
                        <span className="text-xs font-semibold">
                            {loading
                                ? 'กำลังค้นหา…'
                                : hasRun
                                    ? `ผลลัพธ์ ${results.length} หุ้น`
                                    : 'กด ▶ Run Screen เพื่อเริ่มค้นหา'}
                        </span>
                        <button className="btn-outline py-1 flex items-center gap-1.5"><Download size={12} /> Export CSV</button>
                    </div>
                    <table className="w-full">
                        <thead>
                            <tr className="text-[10px] border-b" style={{ color: 'var(--color-text-sub)', borderColor: 'var(--color-border)' }}>
                                {['Symbol', 'ชื่อบริษัท', 'ราคา', 'เปลี่ยนแปลง', 'RSI', 'MACD', 'Volume', 'Signal'].map((h) => (
                                    <th key={h} className="text-left px-4 py-2 font-medium">{h}</th>
                                ))}
                            </tr>
                        </thead>
                        <tbody>
                            {loading ? (
                                [1, 2, 3, 4, 5].map((i) => (
                                    <tr key={i} className="border-b animate-pulse" style={{ borderColor: 'var(--color-border)' }}>
                                        {Array(8).fill(0).map((_, j) => (
                                            <td key={j} className="px-4 py-3">
                                                <div className="h-4 rounded" style={{ background: 'var(--color-hover)' }}></div>
                                            </td>
                                        ))}
                                    </tr>
                                ))
                            ) : error ? (
                                <tr>
                                    <td colSpan={8} className="text-center py-10 text-xs" style={{ color: 'var(--color-red)' }}>
                                        {error}
                                    </td>
                                </tr>
                            ) : !hasRun ? (
                                <tr>
                                    <td colSpan={8} className="text-center py-16 text-sm" style={{ color: 'var(--color-text-sub)' }}>
                                        ตั้งค่าเงื่อนไขแล้วกด ▶ Run Screen
                                    </td>
                                </tr>
                            ) : results.length === 0 ? (
                                <tr>
                                    <td colSpan={8} className="text-center py-16 text-sm" style={{ color: 'var(--color-text-sub)' }}>
                                        ไม่พบหุ้นที่ตรงกับเงื่อนไข
                                    </td>
                                </tr>
                            ) : (
                                results.map((r) => {
                                    const sig = SIGNAL_STYLE[r.signal] || SIGNAL_STYLE['Neutral'];
                                    return (
                                        <tr
                                            key={r.sym}
                                            className="border-b text-xs cursor-pointer transition-colors"
                                            style={{ borderColor: 'var(--color-border)' }}
                                            onClick={() => handleRowClick(r)}
                                            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-hover)')}
                                            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                                        >
                                            <td className="px-4 py-3 font-semibold" style={{ color: 'var(--color-accent)' }}>{r.sym}</td>
                                            <td className="px-4 py-3" style={{ color: 'var(--color-text-sub)' }}>{r.name}</td>
                                            <td className="px-4 py-3 font-medium tabular-nums">{r.price}</td>
                                            <td className="px-4 py-3 font-medium tabular-nums" style={{ color: r.up ? 'var(--color-green)' : 'var(--color-red)' }}>{r.chg}</td>
                                            <td className="px-4 py-3 font-medium tabular-nums" style={{ color: r.rsi < 30 ? 'var(--color-green)' : r.rsi > 70 ? 'var(--color-red)' : 'var(--color-text)' }}>
                                                {typeof r.rsi === 'number' ? r.rsi.toFixed(1) : r.rsi}
                                            </td>
                                            <td className="px-4 py-3" style={{ color: r.macd === 'Buy' || r.macd === 'Strong Buy' ? 'var(--color-green)' : r.macd === 'Sell' ? 'var(--color-red)' : 'var(--color-text-sub)' }}>{r.macd}</td>
                                            <td className="px-4 py-3" style={{ color: 'var(--color-yellow)' }}>{r.vol}</td>
                                            <td className="px-4 py-3">
                                                <span className="badge text-[10px]" style={{ background: sig.bg, color: sig.color }}>{r.signal}</span>
                                            </td>
                                        </tr>
                                    );
                                })
                            )}
                        </tbody>
                    </table>
                </div>
            </div>
        </div>
    );
}
