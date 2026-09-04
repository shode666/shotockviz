import { useCallback, useRef, useState } from 'react';
import { PanelRight } from 'lucide-react';
import useAppStore from '@/store/appStore';
import TradingChart from '@/components/chart/TradingChart';
import ChartToolbar from '@/components/chart/ChartToolbar';
import DrawingToolbar from '@/components/chart/DrawingToolbar';
import RightPanel from '@/components/chart/RightPanel';

interface CrosshairData {
    open?: number;
    high?: number;
    low?: number;
    close?: number;
    volume?: number;
    isUp?: boolean;
}

function fmt(n?: number) {
    if (n == null) return '—';
    return n >= 1000 ? n.toLocaleString('en-US', { maximumFractionDigits: 2 }) : n.toFixed(2);
}

function fmtVol(n?: number) {
    if (n == null) return '—';
    if (n >= 1e9) return (n / 1e9).toFixed(1) + 'B';
    if (n >= 1e6) return (n / 1e6).toFixed(1) + 'M';
    if (n >= 1e3) return (n / 1e3).toFixed(0) + 'K';
    return String(n);
}

export default function ChartPage() {
    const { selectedStock } = useAppStore();
    const [selectedTF, setSelectedTF] = useState('1D');
    const [chartType, setChartType] = useState('candlestick');
    // RSI 14 + MACD default-on: replaces the old BottomPanel tabs as the
    // "under the chart" indicator strips (bd:ux-2026-09 g2, per 04-decisions.md)
    const [activeIndicators, setActiveIndicators] = useState<string[]>(['RSI 14', 'MACD']);
    // S/R levels hidden by default on open (bd:features-2026-09 slice 2,
    // user-confirmed product decision — in-memory toggle only, no persistence).
    const [showSrLevels, setShowSrLevels] = useState(false);
    const [crosshair, setCrosshair] = useState<CrosshairData | null>(null);
    const [isChartLoading, setIsChartLoading] = useState(false);
    const [rightPanelOpen, setRightPanelOpen] = useState(false);
    const rightPanelToggleRef = useRef<HTMLButtonElement>(null);

    // Single close path for the X button, Escape and the mobile backdrop
    // (all three call RightPanel's onClose prop) — bd:ux-2026-09 Chris review
    // (Q-UX2): focus must return to the trigger, not fall through to
    // document.body when the just-clicked close button goes `inert`.
    const closeRightPanel = useCallback(() => {
        setRightPanelOpen(false);
        rightPanelToggleRef.current?.focus();
    }, []);

    return (
        <div className="flex flex-1 overflow-hidden">
            <div className="flex-1 flex flex-col overflow-hidden">
                <ChartToolbar
                    selectedStock={selectedStock}
                    selectedTF={selectedTF}
                    onTFChange={setSelectedTF}
                    chartType={chartType}
                    onChartTypeChange={setChartType}
                    activeIndicators={activeIndicators}
                    onIndicatorToggle={(ind) => {
                        setActiveIndicators(prev =>
                            prev.includes(ind) ? prev.filter(i => i !== ind) : [...prev, ind]
                        );
                    }}
                    isLoading={isChartLoading}
                    showSrLevels={showSrLevels}
                    onToggleSrLevels={() => setShowSrLevels((v) => !v)}
                />
                <DrawingToolbar />

                {/* Chart area */}
                <div className="flex-1 overflow-hidden relative">
                    <TradingChart
                        timeframe={selectedTF}
                        chartType={chartType}
                        activeIndicators={activeIndicators}
                        onCrosshairMove={setCrosshair}
                        onLoadingChange={setIsChartLoading}
                        showSrLevels={showSrLevels}
                    />

                    {/* Crosshair OHLCV overlay */}
                    <div
                        className="absolute top-3 left-3 panel border rounded-xl px-3 py-2 text-xs pointer-events-none transition-opacity"
                        style={{
                            borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)',
                            opacity: crosshair ? 1 : 0.45,
                        }}
                    >
                        <div className="flex gap-3">
                            <span style={{ color: 'var(--color-text-sub)' }}>O: <span style={{ color: crosshair?.isUp ? 'var(--color-green)' : 'var(--color-red)' }}>{fmt(crosshair?.open)}</span></span>
                            <span style={{ color: 'var(--color-text-sub)' }}>H: <span style={{ color: 'var(--color-green)' }}>{fmt(crosshair?.high)}</span></span>
                            <span style={{ color: 'var(--color-text-sub)' }}>L: <span style={{ color: 'var(--color-red)' }}>{fmt(crosshair?.low)}</span></span>
                            <span style={{ color: 'var(--color-text-sub)' }}>C: <span style={{ color: crosshair?.isUp ? 'var(--color-green)' : 'var(--color-red)' }}>{fmt(crosshair?.close)}</span></span>
                            <span style={{ color: 'var(--color-text-sub)' }}>Vol: <span>{fmtVol(crosshair?.volume)}</span></span>
                        </div>
                    </div>

                    {/* RightPanel toggle — panel is an overlay/bottom-sheet (never docked),
                        so News/Portfolio/Fundamentals/Notes/Info stay reachable without
                        eating chart width on desktop or half the screen on mobile (Uma #5).
                        bd:ux-2026-09 Quinn Q-UX1 — lightweight-charts' price-axis <canvas>
                        (right edge) sets its own `z-index: 2` [output: elementFromPoint at
                        the button's coords, tests/e2e/diag.tmp.js] and painted over this
                        button since it had no z-index (auto=0). z-index: 20 wins regardless
                        of that library's internal value. */}
                    <button
                        ref={rightPanelToggleRef}
                        onClick={() => setRightPanelOpen(v => !v)}
                        className="absolute top-3 right-3 panel border rounded-xl p-2 transition-colors hover:bg-[var(--color-hover)]"
                        style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)', zIndex: 20 }}
                        aria-label={rightPanelOpen ? 'ปิดแผงข้อมูล' : 'เปิดแผงข้อมูล'}
                        aria-expanded={rightPanelOpen}
                    >
                        <PanelRight size={14} strokeWidth={2} aria-hidden="true" style={{ color: rightPanelOpen ? 'var(--color-accent)' : 'var(--color-text-sub)' }} />
                    </button>
                </div>
            </div>

            <RightPanel selectedStock={selectedStock} isOpen={rightPanelOpen} onClose={closeRightPanel} />
        </div>
    );
}
