import { useEffect, useRef, useState } from 'react';
import useAppStore from '@/store/appStore';
import stockService from '@/services/stockService';

/**
 * Normalize bar time: if it's a unix timestamp (number), convert to "yyyy-mm-dd".
 * TradingView Lightweight Charts expects either "yyyy-mm-dd" or a UTCTimestamp number.
 * We standardize to "yyyy-mm-dd" for daily bars to avoid ambiguity.
 */
function normalizeBarTime(bar: any): any {
    const t = bar.time;
    // If time is a number (or numeric string) that looks like a unix timestamp, convert to yyyy-mm-dd
    const numVal = typeof t === 'number' ? t : (typeof t === 'string' && /^\d{8,}$/.test(t) ? Number(t) : 0);
    if (numVal > 19000000) {
        const d = new Date(numVal * 1000);
        const yyyy = d.getUTCFullYear();
        const mm = String(d.getUTCMonth() + 1).padStart(2, '0');
        const dd = String(d.getUTCDate()).padStart(2, '0');
        return { ...bar, time: `${yyyy}-${mm}-${dd}` };
    }
    return bar;
}

/** Sort bars ascending by time — safety net for mismatched API ordering */
function sortBarsAsc(bars: any[]) {
    return [...bars].map(normalizeBarTime).sort((a, b) => {
        const ta = typeof a.time === 'string' ? a.time : String(a.time);
        const tb = typeof b.time === 'string' ? b.time : String(b.time);
        return ta < tb ? -1 : ta > tb ? 1 : 0;
    });
}

// Minimal fallback shown ONLY on network error (not on empty API response)
const ERROR_BARS = [
    { time: '2024-11-15', open: 60, high: 75, low: 55, close: 70 },
    { time: '2024-11-16', open: 70, high: 80, low: 65, close: 72 },
    { time: '2024-11-17', open: 72, high: 85, low: 68, close: 80 },
    { time: '2024-11-18', open: 80, high: 88, low: 70, close: 68 },
    { time: '2024-11-19', open: 68, high: 74, low: 60, close: 65 },
];

interface UseChartDataReturn {
    bars: any[];
    isLoading: boolean;
    error: string | null;
    isTimeout: boolean;
    isFund: boolean;
    refetch: () => void;
}

interface UseChartDataProps {
    timeframe?: string;
    onLoadingChange?: (loading: boolean) => void;
}

/**
 * Custom hook: Fetch and manage chart data with retry logic and WebSocket support.
 * Encapsulates all data-fetching concerns for the chart.
 *
 * Returns:
 * - bars: Array of OHLCV bars, sorted by time, normalized
 * - isLoading: true while fetching (false on retry attempts)
 * - error: null or error message
 * - isTimeout: true if request timed out
 * - isFund: true if the stock is a mutual fund (no chart data available)
 * - refetch: Function to manually trigger a refresh
 */
export function useChartData({ timeframe = '1D', onLoadingChange }: UseChartDataProps = {}): UseChartDataReturn {
    const { selectedStock, dataVersion } = useAppStore();
    const [bars, setBars] = useState<any[]>([]);
    const [isLoading, setIsLoading] = useState(false);
    const [error, setError] = useState<string | null>(null);
    const [isTimeout, setIsTimeout] = useState(false);
    const [isFund, setIsFund] = useState(false);

    // loadData is exposed via ref so the retry button can call it outside useEffect
    const loadDataRef = useRef<() => void>(() => {});

    // Track previous symbol+tf to detect silent refreshes (dataVersion change only)
    const prevKeyRef = useRef(`${selectedStock.sym}:${timeframe}`);

    // Fetch data when stock or timeframe changes — auto-retries up to 3× if empty
    // Also re-fetches on dataVersion change (WS data_ready) but silently (no loading flash)
    useEffect(() => {
        let cancelled = false;
        let retryCount = 0;
        let retryTimer: ReturnType<typeof setTimeout> | null = null;
        const MAX_RETRIES = 3;
        const RETRY_DELAY_MS = 4000;
        const currentKey = `${selectedStock.sym}:${timeframe}`;
        const isSilentRefresh = prevKeyRef.current === currentKey && bars.length > 0;
        prevKeyRef.current = currentKey;

        async function loadData() {
            if (retryCount === 0 && !isSilentRefresh) {
                setIsLoading(true);
                onLoadingChange?.(true);
                setError(null);
                setIsFund(false);
                setIsTimeout(false); // reset timeout on each fresh load
                setBars([]); // Clear immediately so old chart doesn't linger
            }
            try {
                const { data } = await stockService.getHistory(selectedStock.sym, timeframe);
                if (cancelled) return;

                // Thai mutual funds — no chart data available, stop immediately
                if (data.is_fund) {
                    setBars([]);
                    setIsFund(true);
                    setError(null);
                    setIsLoading(false);
                    onLoadingChange?.(false);
                    return;
                }

                if (data.bars?.length > 0) {
                    setBars(sortBarsAsc(data.bars));
                    setError(null);
                    setIsFund(false);
                    setIsTimeout(false);
                    setIsLoading(false);
                    onLoadingChange?.(false);
                } else if (retryCount < MAX_RETRIES) {
                    // Empty response — backend may still be fetching history; retry
                    retryCount++;
                    console.info(`[useChartData] No bars for ${selectedStock.sym} ${timeframe}, retry ${retryCount}/${MAX_RETRIES} in ${RETRY_DELAY_MS / 1000}s`);
                    retryTimer = setTimeout(() => { if (!cancelled) loadData(); }, RETRY_DELAY_MS);
                } else {
                    console.warn(`[useChartData] No bars returned for ${selectedStock.sym} ${timeframe}`);
                    setBars([]);
                    setError('No data available');
                    setIsTimeout(false);
                    setIsLoading(false);
                    onLoadingChange?.(false);
                }
            } catch (err: any) {
                if (!cancelled) {
                    const isTimeoutErr = err?.code === 'ECONNABORTED' || err?.message?.includes('timeout');
                    if (isTimeoutErr) {
                        console.warn(`[useChartData] Request timed out for ${selectedStock.sym} ${timeframe}`);
                        setIsTimeout(true);
                        setBars([]);
                        setError('Request timed out');
                        setIsLoading(false);
                        onLoadingChange?.(false);
                    } else {
                        console.error(`[useChartData] Failed to fetch ${selectedStock.sym} ${timeframe}:`, err);
                        setBars(ERROR_BARS);
                        setError(null); // Network error falls back to demo data
                        setIsTimeout(false);
                        setIsLoading(false);
                        onLoadingChange?.(false);
                    }
                }
            }
        }

        // Expose loadData so the refetch function can trigger it
        loadDataRef.current = () => {
            if (cancelled) return;
            retryCount = 0;
            loadData();
        };

        loadData();
        return () => {
            cancelled = true;
            if (retryTimer) clearTimeout(retryTimer);
        };
    }, [selectedStock.sym, timeframe, dataVersion, onLoadingChange]);

    const refetch = () => {
        setIsTimeout(false);
        setIsLoading(true);
        setBars([]);
        loadDataRef.current();
    };

    return { bars, isLoading, error, isTimeout, isFund, refetch };
}
