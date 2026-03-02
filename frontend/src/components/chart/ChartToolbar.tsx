import { CandlestickChart, TrendingUp, AreaChart } from 'lucide-react';

const timeframes = ['1m', '5m', '15m', '1h', '4h', '1D', '1W', '1M'];
const chartTypes = [
    { Icon: CandlestickChart, type: 'candlestick', title: 'Candlestick' },
    { Icon: TrendingUp, type: 'line', title: 'Line' },
    { Icon: AreaChart, type: 'area', title: 'Area' },
];
const indicators = ['Volume', 'MA 20', 'EMA 50', 'RSI 14', 'VWAP', 'MACD', 'BB'];

export default function ChartToolbar({
    selectedStock,
    selectedTF,
    onTFChange,
    chartType,
    onChartTypeChange,
    activeIndicators = [],
    onIndicatorToggle,
}) {
    return (
        <div
            className="panel border-b flex items-center gap-3 px-4 py-2 flex-wrap"
            style={{ borderBottomWidth: 1, borderBottomStyle: 'solid' }}
        >
            {/* Stock info */}
            <div className="flex items-center gap-2 mr-2">
                <span className="font-bold text-sm">{selectedStock.sym}</span>
                <span
                    className="text-sm font-bold"
                    style={{ color: selectedStock.up ? 'var(--color-green)' : 'var(--color-red)' }}
                >
                    {selectedStock.price}
                </span>
                <span
                    className="badge text-xs"
                    style={{
                        background: selectedStock.up ? 'rgba(52,211,153,0.15)' : 'rgba(248,113,113,0.15)',
                        color: selectedStock.up ? 'var(--color-green)' : 'var(--color-red)',
                    }}
                >
                    {selectedStock.chg} {selectedStock.pct}
                </span>
            </div>

            <div className="w-px h-4" style={{ background: 'var(--color-border)' }} />

            {/* Timeframes */}
            <div className="flex gap-1">
                {timeframes.map((tf) => (
                    <button
                        key={tf}
                        onClick={() => onTFChange(tf)}
                        className="text-xs px-2 py-1 rounded-lg font-medium transition-all cursor-pointer"
                        style={selectedTF === tf
                            ? {
                                background: 'var(--color-accent)',
                                color: '#fff',
                                border: '1px solid var(--color-accent)',
                            }
                            : {
                                color: 'var(--color-text-sub)',
                                border: '1px solid transparent',
                                background: 'transparent',
                            }
                        }
                        onMouseEnter={(e) => { if (selectedTF !== tf) e.currentTarget.style.background = 'var(--color-hover)'; }}
                        onMouseLeave={(e) => { if (selectedTF !== tf) e.currentTarget.style.background = 'transparent'; }}
                    >
                        {tf}
                    </button>
                ))}
            </div>

            <div className="w-px h-4" style={{ background: 'var(--color-border)' }} />

            {/* Chart types */}
            <div className="flex gap-1">
                {chartTypes.map(({ Icon, type, title }) => (
                    <button
                        key={type}
                        onClick={() => onChartTypeChange(type)}
                        title={title}
                        className={`flex items-center justify-center p-1.5 rounded-lg cursor-pointer transition-all ${chartType === type ? 'btn-accent' : ''}`}
                        style={chartType !== type ? { color: 'var(--color-text-sub)' } : {}}
                        onMouseEnter={(e) => { if (chartType !== type) e.currentTarget.style.background = 'var(--color-hover)'; }}
                        onMouseLeave={(e) => { if (chartType !== type) e.currentTarget.style.background = 'transparent'; }}
                    >
                        <Icon size={14} />
                    </button>
                ))}
            </div>

            <div className="w-px h-4" style={{ background: 'var(--color-border)' }} />

            {/* Indicators */}
            <div className="flex gap-1">
                {indicators.map((ind) => {
                    const isActive = activeIndicators.includes(ind);
                    return (
                        <button
                            key={ind}
                            onClick={() => onIndicatorToggle?.(ind)}
                            className={`text-xs px-2 py-0.5 rounded-full cursor-pointer transition-colors ${isActive ? 'bg-violet-500 text-white border-transparent' : 'btn-outline border-violet-500/30 text-violet-400 hover:bg-violet-500/20'}`}
                        >
                            {ind}
                        </button>
                    );
                })}
            </div>
        </div>
    );
}
