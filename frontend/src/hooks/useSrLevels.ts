import { useCallback, useEffect, useState } from 'react';
import useAppStore from '@/store/appStore';
import stockService from '@/services/stockService';

export interface SrLevel {
    id: number;
    symbol: string;
    price: number;
    level_type: 'support' | 'resistance';
    tag: string | null;
    color: string | null;
    source: string;
}

interface UseSrLevelsReturn {
    srLevels: SrLevel[];
    /** bd:shotockviz-474 — re-run the fetch for the current symbol (e.g.
     * after creating/deleting a user-owned level). Same request the
     * symbol-change effect makes; no separate code path to drift out of sync. */
    refetch: () => void;
}

/**
 * Fetch support/resistance price levels for the currently selected symbol.
 * bd:features-2026-09 slice 2 — GET /sr-levels/{symbol}, all sources this
 * caller is allowed to see (public sources always; own user_created rows
 * too when authenticated — see backend/api/routes/sr_levels.py).
 *
 * Kept intentionally minimal (no retry/timeout ladder like useChartData) —
 * this is a lightweight decoration fetch, not the primary chart data path;
 * a failed fetch here just means no S/R lines render, silent per
 * services/api.ts SILENT_PATHS.
 */
export function useSrLevels(): UseSrLevelsReturn {
    const { selectedStock } = useAppStore();
    const [srLevels, setSrLevels] = useState<SrLevel[]>([]);
    const [reloadKey, setReloadKey] = useState(0);

    useEffect(() => {
        let cancelled = false;
        setSrLevels([]); // clear immediately so old symbol's levels don't linger

        stockService.getSrLevels(selectedStock.sym)
            .then(({ data }: { data: SrLevel[] }) => {
                if (!cancelled) setSrLevels(data ?? []);
            })
            .catch(() => {
                if (!cancelled) setSrLevels([]);
            });

        return () => { cancelled = true; };
    }, [selectedStock.sym, reloadKey]);

    const refetch = useCallback(() => setReloadKey((k) => k + 1), []);

    return { srLevels, refetch };
}
