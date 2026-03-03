import { useEffect, useRef } from 'react';
import { createChart, CandlestickSeries, LineSeries, AreaSeries, HistogramSeries } from 'lightweight-charts';
import useAppStore from '@/store/appStore';
import { calculateSMA, calculateEMA, calculateRSI, calculateMACD, calculateBollingerBands, calculateVWAP } from '@/utils/indicators';
import { useChartData } from '@/hooks/useChartData';

export default function TradingChart({ timeframe = '1D', chartType = 'candlestick', activeIndicators = [], onCrosshairMove = null, onLoadingChange = null }) {
    const containerRef = useRef(null);
    const chartRef = useRef(null);
    const seriesRef = useRef(null);
    const volumeRef = useRef(null);
    const indicatorsRef = useRef({}); // Store references to indicator series
    const { selectedStock, darkMode } = useAppStore();

    // Fetch chart data using custom hook
    const { bars, isLoading, isTimeout, isFund, refetch } = useChartData({
        timeframe,
        onLoadingChange
    });

    // Determine if we should show "no data" state
    // Show it when: bars are empty AND (it's a fund OR there's an error AND not loading/timeout)
    const noData = bars.length === 0 && (isFund || (isLoading === false && isTimeout === false));

    // Create chart
    useEffect(() => {
        if (!containerRef.current) return;

        const bgColor = darkMode ? '#0d0f17' : '#f8f9fc';
        const textColor = darkMode ? '#9ca3af' : '#6b7280';
        const gridColor = darkMode ? '#1e223520' : '#e5e7eb40';

        const chart = createChart(containerRef.current, {
            width: containerRef.current.clientWidth,
            height: containerRef.current.clientHeight,
            layout: {
                background: { color: bgColor },
                textColor,
                fontFamily: "'Inter', sans-serif",
                fontSize: 11,
            },
            grid: {
                vertLines: { color: gridColor },
                horzLines: { color: gridColor },
            },
            rightPriceScale: {
                borderColor: gridColor,
                scaleMargins: { top: 0.1, bottom: 0.25 },
            },
            timeScale: {
                borderColor: gridColor,
                timeVisible: true,
                secondsVisible: false,
            },
            crosshair: {
                mode: 0,
                vertLine: { color: '#6366f180', width: 1, style: 3, labelBackgroundColor: '#6366f1' },
                horzLine: { color: '#6366f180', width: 1, style: 3, labelBackgroundColor: '#6366f1' },
            },
        });

        chartRef.current = chart;

        // Crosshair move → update OHLCV overlay
        chart.subscribeCrosshairMove((param) => {
            if (!onCrosshairMove) return;
            if (!param || !param.time || !param.seriesData) {
                onCrosshairMove(null);
                return;
            }
            // Try to get candlestick data from main series
            const mainSeries = seriesRef.current;
            if (!mainSeries) return;
            const bar = param.seriesData.get(mainSeries);
            if (!bar) return;
            const isCandle = 'open' in bar;
            if (isCandle) {
                onCrosshairMove({
                    open: bar.open,
                    high: bar.high,
                    low: bar.low,
                    close: bar.close,
                    volume: volumeRef.current ? param.seriesData.get(volumeRef.current)?.value : undefined,
                    isUp: bar.close >= bar.open,
                });
            } else {
                // Line/area: only has value
                onCrosshairMove({ close: bar.value, isUp: true });
            }
        });

        // Main series
        let series;
        if (chartType === 'line') {
            series = chart.addSeries(LineSeries, {
                color: '#6366f1',
                lineWidth: 2,
            });
        } else if (chartType === 'area') {
            series = chart.addSeries(AreaSeries, {
                topColor: 'rgba(99, 102, 241, 0.4)',
                bottomColor: 'rgba(99, 102, 241, 0.05)',
                lineColor: '#6366f1',
                lineWidth: 2,
            });
        } else {
            series = chart.addSeries(CandlestickSeries, {
                upColor: '#34d399',
                downColor: '#f87171',
                borderDownColor: '#f87171',
                borderUpColor: '#34d399',
                wickDownColor: '#f87171',
                wickUpColor: '#34d399',
            });
        }
        seriesRef.current = series;

        // Volume (only create if not in indicators - will be managed by indicator system)
        const volumeSeries = chart.addSeries(HistogramSeries, {
            color: '#26a69a',
            priceFormat: { type: 'volume' },
            priceScaleId: 'volume',
        });
        chart.priceScale('volume').applyOptions({
            scaleMargins: { top: 0.8, bottom: 0 },
        });
        volumeRef.current = volumeSeries;

        // Resize observer
        const ro = new ResizeObserver(() => {
            if (containerRef.current) {
                chart.applyOptions({
                    width: containerRef.current.clientWidth,
                    height: containerRef.current.clientHeight,
                });
            }
        });
        ro.observe(containerRef.current);

        return () => {
            ro.disconnect();
            chart.remove();
        };
    }, [darkMode, chartType]);

    // Update data
    useEffect(() => {
        if (!seriesRef.current || !volumeRef.current) return;

        // When bars is empty (loading new stock or no data) — wipe chart series so old data doesn't linger
        if (bars.length === 0) {
            seriesRef.current.setData([]);
            volumeRef.current.setData([]);
            // Also remove all indicator series
            const chart = chartRef.current;
            const currentInds = indicatorsRef.current;
            if (chart) {
                Object.keys(currentInds).forEach((key) => {
                    if (Array.isArray(currentInds[key])) {
                        currentInds[key].forEach((s: any) => { try { chart.removeSeries(s); } catch {} });
                    } else {
                        try { chart.removeSeries(currentInds[key]); } catch {}
                    }
                    delete currentInds[key];
                });
            }
            return;
        }

        if (chartType === 'line' || chartType === 'area') {
            seriesRef.current.setData(
                bars.map((b) => ({ time: b.time, value: b.close })),
            );
        } else {
            seriesRef.current.setData(bars);
        }

        // Show volume based on 'Volume' indicator toggle
        if (activeIndicators.includes('Volume')) {
            volumeRef.current.setData(
                bars.map((b) => ({
                    time: b.time,
                    value: b.volume || 0,
                    color: b.close >= b.open ? '#34d39966' : '#f8717166',
                })),
            );
        } else {
            volumeRef.current.setData([]);
        }

        // Update Indicators
        const chart = chartRef.current;
        const currentInds = indicatorsRef.current;

        // Remove inactive indicators
        Object.keys(currentInds).forEach((key) => {
            if (!activeIndicators.includes(key) || bars.length === 0) {
                if (Array.isArray(currentInds[key])) {
                    currentInds[key].forEach(s => chart.removeSeries(s));
                } else {
                    chart.removeSeries(currentInds[key]);
                }
                delete currentInds[key];
            }
        });

        if (bars.length > 0) {
            // Apply SMA 20
            if (activeIndicators.includes('MA 20')) {
                if (!currentInds['MA 20']) {
                    currentInds['MA 20'] = chart.addSeries(LineSeries, { color: '#f59e0b', lineWidth: 2, crosshairMarkerVisible: false });
                }
                currentInds['MA 20'].setData(calculateSMA(bars, 20));
            }

            // Apply EMA 50
            if (activeIndicators.includes('EMA 50')) {
                if (!currentInds['EMA 50']) {
                    currentInds['EMA 50'] = chart.addSeries(LineSeries, { color: '#3b82f6', lineWidth: 2, crosshairMarkerVisible: false });
                }
                currentInds['EMA 50'].setData(calculateEMA(bars, 50));
            }

            // Apply RSI 14
            if (activeIndicators.includes('RSI 14')) {
                if (!currentInds['RSI 14']) {
                    currentInds['RSI 14'] = chart.addSeries(LineSeries, {
                        color: '#a855f7', lineWidth: 2, crosshairMarkerVisible: false, priceScaleId: 'rsi'
                    });
                    chart.priceScale('rsi').applyOptions({
                        scaleMargins: { top: 0.8, bottom: 0 },
                    });
                }
                currentInds['RSI 14'].setData(calculateRSI(bars, 14));
            }

            // Apply VWAP (intraday only: 1m, 5m, 15m, 1h, 4h)
            const isIntraday = ['1m', '5m', '15m', '1h', '4h'].includes(timeframe);
            if (activeIndicators.includes('VWAP') && isIntraday) {
                if (!currentInds['VWAP']) {
                    currentInds['VWAP'] = chart.addSeries(LineSeries, {
                        color: '#9C27B0', lineWidth: 2, lineStyle: 2, crosshairMarkerVisible: false
                    });
                }
                currentInds['VWAP'].setData(calculateVWAP(bars));
            }

            // Apply MACD
            if (activeIndicators.includes('MACD')) {
                if (!currentInds['MACD']) {
                    const macdLine = chart.addSeries(LineSeries, { color: '#2962FF', lineWidth: 1.5, crosshairMarkerVisible: false, priceScaleId: 'macd' });
                    const signalLine = chart.addSeries(LineSeries, { color: '#FF6D00', lineWidth: 1.5, crosshairMarkerVisible: false, priceScaleId: 'macd' });
                    const hist = chart.addSeries(HistogramSeries, { priceScaleId: 'macd' });

                    chart.priceScale('macd').applyOptions({
                        scaleMargins: { top: 0.8, bottom: 0 },
                    });
                    currentInds['MACD'] = [macdLine, signalLine, hist];
                }
                const macdData = calculateMACD(bars);
                currentInds['MACD'][0].setData(macdData.macdLine);
                currentInds['MACD'][1].setData(macdData.signalLine);
                currentInds['MACD'][2].setData(macdData.histogram);
            }

            // Apply Bollinger Bands
            if (activeIndicators.includes('BB')) {
                if (!currentInds['BB']) {
                    const upper = chart.addSeries(LineSeries, { color: 'rgba(59, 130, 246, 0.5)', lineWidth: 1, crosshairMarkerVisible: false });
                    const lower = chart.addSeries(LineSeries, { color: 'rgba(59, 130, 246, 0.5)', lineWidth: 1, crosshairMarkerVisible: false });
                    currentInds['BB'] = [upper, lower]; // Only drawing lines, filling area between them requires hack in lightweight-charts
                }
                const bbData = calculateBollingerBands(bars);
                currentInds['BB'][0].setData(bbData.upper);
                currentInds['BB'][1].setData(bbData.lower);
            }
        }

        chart.timeScale().fitContent();
    }, [bars, chartType, activeIndicators]);

    return (
        <div className="w-full h-full relative">
            <div ref={containerRef} className="w-full h-full" />

            {/* Loading overlay — semi-opaque so user knows something is happening */}
            {isLoading && (
                <div
                    className="absolute inset-0 flex flex-col items-center justify-center gap-3 pointer-events-none z-10"
                    style={{ background: 'rgba(13,15,23,0.72)', backdropFilter: 'blur(2px)' }}
                >
                    {/* Spinner ring */}
                    <span
                        style={{
                            display: 'block',
                            width: 32, height: 32,
                            border: '3px solid var(--color-border)',
                            borderTopColor: 'var(--color-accent)',
                            borderRadius: '50%',
                            animation: 'spin 0.65s linear infinite',
                        }}
                    />
                    <div className="text-center">
                        <div className="text-xs font-semibold" style={{ color: 'var(--color-text)' }}>
                            กำลังโหลด {selectedStock.sym}…
                        </div>
                        <div className="text-[10px] mt-0.5" style={{ color: 'var(--color-text-sub)' }}>
                            กรุณารอสักครู่
                        </div>
                    </div>
                </div>
            )}

            {/* Timeout overlay — distinct from noData */}
            {isTimeout && !isLoading && (
                <div className="absolute inset-0 flex items-center justify-center z-10" style={{ background: 'var(--color-bg)', opacity: 0.92 }}>
                    <div className="text-center">
                        <div className="text-2xl mb-2">⏱</div>
                        <p className="text-sm font-medium mb-1">Request timed out</p>
                        <p className="text-xs mb-3" style={{ color: 'var(--color-text-sub)' }}>ข้อมูลใช้เวลานานเกินไป — กรุณาลองใหม่</p>
                        <button onClick={refetch} className="btn-accent text-xs px-3 py-1.5">Retry</button>
                    </div>
                </div>
            )}

            {/* No data state — distinct from timeout */}
            {!isLoading && !isTimeout && noData && (
                <div className="absolute inset-0 flex flex-col items-center justify-center gap-4 pointer-events-none">
                    <div
                        className="glass-panel rounded-2xl px-6 py-5 pointer-events-auto text-center"
                        style={{
                            background: 'var(--color-panel)',
                            border: '1px solid var(--color-border)',
                        }}
                    >
                        {isFund ? (
                            <>
                                <span className="text-4xl block mb-3">🏦</span>
                                <div className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                                    กองทุนรวม — ไม่มีข้อมูลกราฟ
                                </div>
                                <div className="text-xs mt-2 mb-4" style={{ color: 'var(--color-text-sub)' }}>
                                    กองทุนไทยไม่มีข้อมูล OHLCV แบบ real-time
                                    <br />
                                    ดูมูลค่า NAV ได้ที่หน้า <span style={{ color: 'var(--color-accent)', fontWeight: 600 }}>Portfolio</span>
                                </div>
                            </>
                        ) : (
                            <>
                                <span className="text-4xl block mb-3">📊</span>
                                <div className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>
                                    No data available
                                </div>
                                <div className="text-xs mt-2 mb-4" style={{ color: 'var(--color-text-sub)' }}>
                                    Yahoo Finance may be rate limiting.
                                    <br />
                                    Try clicking a US stock like <span style={{ color: 'var(--color-accent)', fontWeight: 600 }}>NVDA</span> or <span style={{ color: 'var(--color-accent)', fontWeight: 600 }}>AAPL</span>.
                                </div>
                            </>
                        )}
                        {!isFund && (
                            <button
                                className="text-xs px-3 py-1.5 rounded-lg transition-all"
                                style={{
                                    background: 'var(--color-accent)',
                                    color: '#fff',
                                    cursor: 'pointer',
                                    border: 'none',
                                }}
                                onClick={refetch}
                            >
                                Try Again
                            </button>
                        )}
                    </div>
                </div>
            )}
        </div>
    );
}
