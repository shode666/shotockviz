import { CandlestickChart, TrendingUp, AreaChart, Loader2, Rows3, Plus, X } from 'lucide-react';
import { parseSymbol, MARKET_COLORS } from '@/utils/formatters';
import { isVwapAvailable } from '@/utils/indicators';

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
    // bd:shotockviz-474 — user-owned horizontal S/R levels. `isAuthenticated`
    // gates the "+ Level" control the same honest way F5 gated VWAP on
    // non-intraday timeframes: visible, but disabled + a title that says why,
    // never a button that looks clickable and silently does nothing.
    isAuthenticated = false,
    onAddLevel,
    userLevels = [],
    onDeleteLevel,
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
                            aria-pressed={isActive}
                            className={`text-xs px-2 py-1 rounded-lg font-medium whitespace-nowrap transition-all cursor-pointer flex items-center gap-1 ${isActive ? 'btn-accent' : ''}`}
                            style={!isActive
                                ? { color: 'var(--color-text-sub)', border: '1px solid transparent', background: 'transparent' }
                                : undefined
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
                    const isDisabled = ind === 'VWAP' && !isVwapAvailable(selectedTF);
                    return (
                        <button
                            key={ind}
                            onClick={() => onIndicatorToggle?.(ind)}
                            disabled={isDisabled}
                            title={isDisabled ? 'VWAP is intraday-only' : ind}
                            aria-label={ind}
                            aria-pressed={isActive}
                            aria-disabled={isDisabled}
                            className={`text-xs px-2.5 py-1 rounded-lg whitespace-nowrap transition-colors ${isDisabled ? 'opacity-40 cursor-not-allowed btn-outline border-violet-500/30 text-violet-400' : `cursor-pointer ${isActive ? 'bg-[var(--color-accent-strong)] text-white border-transparent' : 'btn-outline border-violet-500/30 text-violet-400 hover:bg-violet-500/20'}`}`}
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

            {/* Add horizontal level — bd:shotockviz-474. Logged-out users get
                the disabled+title pattern (F5 precedent), not a hidden
                control — the button existing at all is honest about the
                feature existing; disabled+title is honest about who can use
                it right now. */}
            <button
                onClick={() => isAuthenticated && onAddLevel?.()}
                disabled={!isAuthenticated}
                aria-disabled={!isAuthenticated}
                title={isAuthenticated ? 'Add a horizontal support/resistance level' : 'Sign in to add a level'}
                aria-label="Add horizontal level"
                className={`flex items-center gap-1 text-xs px-2.5 py-1 rounded-lg whitespace-nowrap transition-colors ${!isAuthenticated ? 'opacity-40 cursor-not-allowed btn-outline border-violet-500/30 text-violet-400' : 'cursor-pointer btn-outline border-violet-500/30 text-violet-400 hover:bg-violet-500/20'}`}
            >
                <Plus size={12} />
                Level
            </button>

            {/* Your levels — only the caller's own user_created rows are ever
                in this list (GET /sr-levels/{symbol} never returns anyone
                else's, see backend/api/routes/sr_levels.py), so every chip
                here is deletable by definition; no per-row ownership check
                needed client-side. Rendered regardless of showSrLevels — the
                management list and the on-chart visibility toggle are two
                different questions (bd:shotockviz-474). */}
            {userLevels.length > 0 && (
                <div className="flex gap-1 items-center flex-wrap" aria-label="Your horizontal levels">
                    {userLevels.map((lvl) => (
                        <span
                            key={lvl.id}
                            className="badge text-[11px] flex items-center gap-1"
                            style={{
                                background: lvl.level_type === 'support' ? 'rgba(234,179,8,0.15)' : 'rgba(217,70,239,0.15)',
                                color: lvl.level_type === 'support' ? '#eab308' : '#d946ef',
                            }}
                        >
                            {lvl.level_type === 'support' ? 'S' : 'R'} {lvl.price}
                            <button
                                onClick={() => onDeleteLevel?.(lvl.id)}
                                aria-label={`Delete ${lvl.level_type} level at ${lvl.price}`}
                                title="Delete this level"
                                className="cursor-pointer"
                                style={{ display: 'inline-flex' }}
                            >
                                <X size={10} />
                            </button>
                        </span>
                    ))}
                </div>
            )}
        </div>
    );
}
