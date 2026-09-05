import { useEffect, useState } from 'react';
import useAppStore from '@/store/appStore';
import { usePriceUpdates } from '@/hooks/usePriceUpdates';
import { parseSymbol } from '@/utils/formatters';
import { getSetStatus, getUsStatus } from '@/utils/marketStatus';
import { getPriceFreshness, PRICE_FRESHNESS_COLOR } from '@/utils/statusBar';

interface StatusBarProps {
    isConnected: boolean;
    isAuthenticated: boolean;
}

export default function StatusBar({ isConnected, isAuthenticated }: StatusBarProps) {
    const selectedSymbol = useAppStore((s) => s.selectedStock.sym);

    // Same 60s cadence + cache as the sidebar/dashboard (usePriceUpdates) —
    // this label now shows real staleness of the symbol on screen, derived
    // from the server `ts` cache_publisher.py:36 stamps into every quote,
    // instead of the always-"—" data_ready-derived path it replaces
    // (bd:shotockviz-09j; see utils/statusBar.ts header for the ADR-UH-001
    // history). Disabled for guests, matching Sidebar's own gating.
    const { prices } = usePriceUpdates(isAuthenticated ? [selectedSymbol] : [], { enabled: isAuthenticated });
    const ts = prices[selectedSymbol]?.ts ?? null;

    // Re-render every 30s purely so an already-known timestamp's *displayed
    // age* advances ("2 นาทีที่แล้ว" -> "3 นาทีที่แล้ว") between polls, without
    // fabricating anything: `ts` still comes from the server, only the "now"
    // diffed against it ticks. This is NOT the F3 anti-pattern the
    // ui-honesty-2026-09 audit removed (a `setInterval` wall clock rendered
    // AS the update time) — the value shown is still a real server
    // timestamp's age, just recomputed periodically.
    const [now, setNow] = useState(() => Date.now());
    useEffect(() => {
        const t = setInterval(() => setNow(Date.now()), 30_000);
        return () => clearInterval(t);
    }, []);

    // Which market-hours model applies, if any (utils/marketStatus.ts only
    // covers SET and US today — ADR-UH-004). `null` means "don't know",
    // which getPriceFreshness treats as "no closed-market override" rather
    // than guessing.
    const market = parseSymbol(selectedSymbol).market;
    const marketOpen =
        market === 'SET' ? getSetStatus().open :
        market === 'US' ? getUsStatus().open :
        null;

    const freshness = getPriceFreshness(ts, now, marketOpen);

    return (
        <div
            className="panel border-t hidden md:flex items-center justify-between px-4 py-1"
            style={{ borderTopWidth: 1, borderTopStyle: 'solid' }}
        >
            <div className="flex items-center gap-4">
                {isAuthenticated && (
                    <>
                        <span
                            className="text-xs"
                            style={{ color: isConnected ? 'var(--color-green)' : 'var(--color-text-sub)' }}
                        >
                            {isConnected ? '● Live' : '○ Offline'}
                        </span>
                        <span className="text-xs" style={{ color: PRICE_FRESHNESS_COLOR[freshness.tone] }}>
                            ราคา {selectedSymbol}: {freshness.label}
                        </span>
                    </>
                )}
            </div>
            <div className="text-xs" style={{ color: 'var(--color-text-sub)' }}>
                ShotockViz v0.1 · Data: yfinance + Finnhub
            </div>
        </div>
    );
}
