import { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import stockService from '@/services/stockService';
import useAppStore from '@/store/appStore';

interface PriceData {
    price?: number;
    change?: number;
    change_pct?: number;
    volume?: number;
    type?: string;
    nav_date?: string;
}

interface UsePriceUpdatesOptions {
    /** Polling interval in ms (default: 60000) */
    interval?: number;
    /** Whether to enable polling (default: true) */
    enabled?: boolean;
    /** Retry delay on error in ms (default: 15000) */
    retryDelay?: number;
    /** Retry delay on partial data in ms (default: 10000) */
    partialRetryDelay?: number;
}

interface UsePriceUpdatesReturn {
    prices: Record<string, PriceData>;
    isLoading: boolean;
    refresh: () => void;
}

/**
 * Custom hook: Polls batch quotes for a list of symbols.
 *
 * Encapsulates interval-based price fetching with:
 * - Configurable polling interval
 * - Auto-retry on partial data or network error
 * - Reacts to dataVersion changes (WS data_ready)
 * - Stable ref-based interval (no recreations)
 * - Array-content memoization (immune to new array references)
 *
 * Usage:
 *   const { prices, refresh } = usePriceUpdates(symbols, { enabled: isAuthenticated });
 */
export function usePriceUpdates(
    symbols: string[],
    options: UsePriceUpdatesOptions = {},
): UsePriceUpdatesReturn {
    const {
        interval = 60_000,
        enabled = true,
        retryDelay = 15_000,
        partialRetryDelay = 10_000,
    } = options;

    const { dataVersion } = useAppStore();
    const [prices, setPrices] = useState<Record<string, PriceData>>({});
    const [isLoading, setIsLoading] = useState(false);

    const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    // Stabilize symbols by content (join → string compare) so that
    // callers like `INDICES_SYMS.map(...)` don't trigger infinite loops.
    const symbolsKey = symbols.join(',');
    const stableSymbols = useMemo(() => symbols, [symbolsKey]);

    // Keep a ref to the latest symbols so the fetch callback always reads
    // current values without needing to be recreated.
    const symbolsRef = useRef(stableSymbols);
    useEffect(() => { symbolsRef.current = stableSymbols; }, [stableSymbols]);

    const enabledRef = useRef(enabled);
    useEffect(() => { enabledRef.current = enabled; }, [enabled]);

    // Stable fetch function — never recreated, reads from refs
    const fetchPrices = useCallback(async () => {
        const syms = symbolsRef.current;
        if (!enabledRef.current || !syms.length) return;

        if (retryTimerRef.current) {
            clearTimeout(retryTimerRef.current);
            retryTimerRef.current = null;
        }

        setIsLoading(true);
        try {
            const r = await stockService.getQuotesBatch(syms);
            const quoteMap: Record<string, PriceData> = r.data ?? {};
            let anyMissing = false;

            setPrices((prev) => {
                const next = { ...prev };
                for (const sym of syms) {
                    if (quoteMap[sym]) next[sym] = quoteMap[sym];
                    else anyMissing = true;
                }
                return next;
            });

            // Retry once for partial data (backend may still be fetching)
            if (anyMissing) {
                retryTimerRef.current = setTimeout(() => fetchPrices(), partialRetryDelay);
            }
        } catch {
            // Network error — retry after delay
            retryTimerRef.current = setTimeout(() => fetchPrices(), retryDelay);
        } finally {
            setIsLoading(false);
        }
    }, [retryDelay, partialRetryDelay]);

    // Polling interval — set up once, stable fetchPrices never changes
    useEffect(() => {
        if (!enabled) return;
        const timer = setInterval(fetchPrices, interval);
        return () => {
            clearInterval(timer);
            if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
        };
    }, [enabled, interval, fetchPrices]);

    // Immediate fetch when symbols actually change (by content) or dataVersion bumps
    useEffect(() => {
        fetchPrices();
    }, [stableSymbols, dataVersion, enabled, fetchPrices]);

    return { prices, isLoading, refresh: fetchPrices };
}
