import { CandlestickChart, TrendingUp, AreaChart, Loader2, Rows3 } from 'lucide-react';
import { parseSymbol, MARKET_COLORS } from '@/utils/formatters';

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
    isLoading = false,
    showSrLevels = false,
    onToggleSrLevels,
}) {
    return (
        <div
            className="panel border-b flex items-center gap-3 px-4 py-2 flex-wrap"
            style={{ borderBottomWidth: 1, borderBottomStyle: 'solid' }}
        >
            {/* Stock info */}
            <div className="flex items-center gap-2 mr-2">
                <span className="font-bold text-sm">{parseSymbol(selectedStock.sym).display}</span>
                {(() => { const p = parseSymbol(selectedStock.sym); const c = MARKET_COLORS[p.market]; return c ? (
                    <span className="badge text-[11px]" style={{ background: c.bg, color: c.text }}>{p.market}</span>
                ) : null; })()}
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
            <div className="flex gap-1 items-center">
                {timeframes.map((tf) => {
                    const isActive = selectedTF === tf;
                    const isLoadingThis = isActive && isLoading;
                    return (
                        <button
                            key={tf}
                            onClick={() => onTFChange(tf)}
                            className="text-xs px-2 py-1 rounded-lg font-medium whitespace-nowrap transition-all cursor-pointer flex items-center gap-1"
                            style={isActive
                                ? { background: 'var(--color-accent-strong)', color: '#fff', border: '1px solid var(--color-accent-strong)' }
                                : { color: 'var(--color-text-sub)', border: '1px solid transparent', background: 'transparent' }
                            }
                            onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = 'var(--color-hover)'; }}
                            onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = 'transparent'; }}
                        >
                            {isLoadingThis
                                ? <Loader2 size={10} style={{ animation: 'spin 0.65s linear infinite' }} />
                                : null
                            }
                            {tf}
                        </button>
                    );
                })}
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

            {/* Indicators — pill shows the short name only (e.g. "MA"); the
                period stays in the value/title/aria-label ("MA 20") since
                TradingChart.tsx keys activeIndicators.includes() off the
                full string (bd:ux-2026-09 user-fix — pills wrapped to 2
                lines / "MA 20" etc; rounded-lg not rounded-full so a 2-char
                label like "BB" doesn't render as a circle). */}
            <div className="flex gap-1">
                {indicators.map((ind) => {
                    const isActive = activeIndicators.includes(ind);
                    const displayLabel = ind.replace(/\s+\d+$/, '');
                    return (
                        <button
                            key={ind}
                            onClick={() => onIndicatorToggle?.(ind)}
                            title={ind}
                            aria-label={ind}
                            aria-pressed={isActive}
                            className={`text-xs px-2.5 py-1 rounded-lg whitespace-nowrap cursor-pointer transition-colors ${isActive ? 'bg-[var(--color-accent-strong)] text-white border-transparent' : 'btn-outline border-violet-500/30 text-violet-400 hover:bg-violet-500/20'}`}
                        >
                            {displayLabel}
                        </button>
                    );
                })}
            </div>

            <div className="w-px h-4" style={{ background: 'var(--color-border)' }} />

            {/* S/R levels toggle — hidden by default (bd:features-2026-09 slice 2,
                user-confirmed product decision). Follows the same pill-button
                pattern as the indicator toggles above. */}
            <button
                onClick={() => onToggleSrLevels?.()}
                title="Toggle support/resistance levels"
                aria-label="Toggle support/resistance levels"
                aria-pressed={showSrLevels}
                className={`flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg whitespace-nowrap cursor-pointer transition-colors ${showSrLevels ? 'bg-[var(--color-accent-strong)] text-white border-transparent' : 'btn-outline border-violet-500/30 text-violet-400 hover:bg-violet-500/20'}`}
            >
                <Rows3 size={12} />
                S/R
            </button>
        </div>
    );
}
