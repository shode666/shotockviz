/**
 * Multi-Chart Layout — supports 1x1, 2x1, 1x2, 2x2 grid configurations.
 *
 * Each cell is an independent chart instance with its own symbol and timeframe.
 * State is managed via appStore.chartSlots.
 */
import { useState, useCallback } from 'react';
import TradingChart from './TradingChart';
import ChartToolbar from './ChartToolbar';
import useAppStore from '@/store/appStore';

type LayoutMode = '1x1' | '2x1' | '1x2' | '2x2';

interface ChartSlot {
    symbol: string;
    timeframe: string;
    chartType: string;
    activeIndicators: string[];
}

const LAYOUT_CONFIGS: Record<LayoutMode, { rows: number; cols: number }> = {
    '1x1': { rows: 1, cols: 1 },
    '2x1': { rows: 1, cols: 2 },
    '1x2': { rows: 2, cols: 1 },
    '2x2': { rows: 2, cols: 2 },
};

const LAYOUT_LABELS: Record<LayoutMode, string> = {
    '1x1': '▢',
    '2x1': '▢▢',
    '1x2': '▢\n▢',
    '2x2': '▢▢\n▢▢',
};

function LayoutIcon({ mode, active }: { mode: LayoutMode; active: boolean }) {
    const { rows, cols } = LAYOUT_CONFIGS[mode];
    const size = 20;
    const gap = 2;
    const cellW = (size - gap * (cols - 1)) / cols;
    const cellH = (size - gap * (rows - 1)) / rows;

    return (
        <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`}>
            {Array.from({ length: rows * cols }, (_, i) => {
                const row = Math.floor(i / cols);
                const col = i % cols;
                return (
                    <rect
                        key={i}
                        x={col * (cellW + gap)}
                        y={row * (cellH + gap)}
                        width={cellW}
                        height={cellH}
                        rx={2}
                        fill={active ? 'var(--color-accent)' : 'var(--color-text-sub)'}
                        opacity={active ? 1 : 0.5}
                    />
                );
            })}
        </svg>
    );
}

export default function MultiChartLayout() {
    const { selectedStock } = useAppStore();

    const [layout, setLayout] = useState<LayoutMode>('1x1');
    const [slots, setSlots] = useState<ChartSlot[]>([
        { symbol: selectedStock.sym, timeframe: '1D', chartType: 'candlestick', activeIndicators: ['Volume'] },
        { symbol: 'AAPL', timeframe: '1D', chartType: 'candlestick', activeIndicators: ['Volume'] },
        { symbol: 'PTT.BK', timeframe: '1D', chartType: 'candlestick', activeIndicators: ['Volume'] },
        { symbol: 'GOOGL', timeframe: '1D', chartType: 'candlestick', activeIndicators: ['Volume'] },
    ]);

    const { rows, cols } = LAYOUT_CONFIGS[layout];
    const cellCount = rows * cols;

    const updateSlot = useCallback((index: number, updates: Partial<ChartSlot>) => {
        setSlots(prev => prev.map((s, i) => i === index ? { ...s, ...updates } : s));
    }, []);

    return (
        <div className="flex flex-col h-full">
            {/* Layout selector */}
            <div
                className="flex items-center gap-2 px-3 py-1.5 border-b"
                style={{ borderColor: 'var(--color-border)' }}
            >
                <span className="text-xs font-medium" style={{ color: 'var(--color-text-sub)' }}>
                    Layout:
                </span>
                {(Object.keys(LAYOUT_CONFIGS) as LayoutMode[]).map((mode) => (
                    <button
                        key={mode}
                        onClick={() => setLayout(mode)}
                        className="p-1 rounded transition-all"
                        style={{
                            background: layout === mode ? 'var(--color-accent-bg)' : 'transparent',
                        }}
                        title={`${mode} layout`}
                    >
                        <LayoutIcon mode={mode} active={layout === mode} />
                    </button>
                ))}
            </div>

            {/* Chart grid */}
            <div
                className="flex-1 grid"
                style={{
                    gridTemplateRows: `repeat(${rows}, 1fr)`,
                    gridTemplateColumns: `repeat(${cols}, 1fr)`,
                    gap: '1px',
                    background: 'var(--color-border)',
                }}
            >
                {Array.from({ length: cellCount }, (_, i) => {
                    const slot = slots[i];
                    return (
                        <div
                            key={`chart-${i}-${slot.symbol}`}
                            className="relative"
                            style={{ background: 'var(--color-bg)', minHeight: 200 }}
                        >
                            {/* Mini symbol selector */}
                            <div
                                className="absolute top-1 left-2 z-20 flex items-center gap-2"
                            >
                                <input
                                    type="text"
                                    value={slot.symbol}
                                    onChange={(e) => updateSlot(i, { symbol: e.target.value.toUpperCase() })}
                                    onKeyDown={(e) => {
                                        if (e.key === 'Enter') {
                                            (e.target as HTMLInputElement).blur();
                                        }
                                    }}
                                    className="text-xs font-mono px-1.5 py-0.5 rounded w-20"
                                    style={{
                                        background: 'var(--color-panel)',
                                        color: 'var(--color-text)',
                                        border: '1px solid var(--color-border)',
                                    }}
                                />
                                <select
                                    value={slot.timeframe}
                                    onChange={(e) => updateSlot(i, { timeframe: e.target.value })}
                                    className="text-xs px-1 py-0.5 rounded"
                                    style={{
                                        background: 'var(--color-panel)',
                                        color: 'var(--color-text)',
                                        border: '1px solid var(--color-border)',
                                    }}
                                >
                                    {['1m', '5m', '15m', '1h', '4h', '1D', '1W', '1M'].map(tf => (
                                        <option key={tf} value={tf}>{tf}</option>
                                    ))}
                                </select>
                            </div>

                            <TradingChart
                                timeframe={slot.timeframe}
                                chartType={slot.chartType}
                                activeIndicators={slot.activeIndicators}
                            />
                        </div>
                    );
                })}
            </div>
        </div>
    );
}

export type { LayoutMode, ChartSlot };
