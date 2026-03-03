import { useState, useEffect, useCallback, useRef } from 'react';
import portfolioService from '@/services/portfolioService';
import useAuthStore from '@/store/authStore';
import useAppStore from '@/store/appStore';

interface UsePortfolioDataReturn {
    analytics: any;
    txns: any[];
    loading: boolean;
    timedOut: boolean;
    reload: () => Promise<void>;
}

/**
 * Custom hook: Fetches portfolio analytics + transactions with auto-retry.
 *
 * Encapsulates:
 * - Parallel fetch of analytics + transactions
 * - Auto-retry for pending prices (up to 6× every 5s)
 * - Reacts to dataVersion changes (WS data_ready)
 * - Timeout detection for UX feedback
 *
 * Usage:
 *   const { analytics, txns, loading, timedOut, reload } = usePortfolioData();
 */
export function usePortfolioData(): UsePortfolioDataReturn {
    const { isAuthenticated } = useAuthStore();
    const dataVersion = useAppStore(s => s.dataVersion);

    const [analytics, setAnalytics] = useState<any>(null);
    const [txns, setTxns] = useState<any[]>([]);
    const [loading, setLoading] = useState(true);
    const [timedOut, setTimedOut] = useState(false);

    const load = useCallback(async () => {
        if (!isAuthenticated) return;
        setLoading(true);
        setTimedOut(false);
        try {
            const [analyticsRes, txnsRes] = await Promise.all([
                portfolioService.getAnalytics(),
                portfolioService.getTransactions(),
            ]);
            setAnalytics(analyticsRes.data);
            setTxns(txnsRes.data ?? []);
        } catch (err: any) {
            if (err?.code === 'ECONNABORTED' || err?.message?.includes('timeout')) {
                setTimedOut(true);
            }
        } finally {
            setLoading(false);
        }
    }, [isAuthenticated]);

    // Initial fetch
    useEffect(() => { load(); }, [load]);

    // Auto-retry: if backend says prices are pending, retry every 5s up to 6 times
    const retryCountRef = useRef(0);
    const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    useEffect(() => {
        if (analytics?.has_pending_prices && retryCountRef.current < 6) {
            retryTimerRef.current = setTimeout(() => {
                retryCountRef.current += 1;
                portfolioService.getAnalytics()
                    .then(res => setAnalytics(res.data))
                    .catch(() => {});
            }, 5000);
        } else if (!analytics?.has_pending_prices) {
            retryCountRef.current = 0;
        }
        return () => {
            if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
        };
    }, [analytics]);

    // Re-fetch when WS data_ready arrives (dataVersion bump)
    const prevDataVersionRef = useRef(dataVersion);
    useEffect(() => {
        if (prevDataVersionRef.current !== dataVersion) {
            prevDataVersionRef.current = dataVersion;
            portfolioService.getAnalytics()
                .then(res => setAnalytics(res.data))
                .catch(() => {});
        }
    }, [dataVersion]);

    return { analytics, txns, loading, timedOut, reload: load };
}
