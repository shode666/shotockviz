import { useState } from 'react';
import useAppStore from '@/store/appStore';
import { formatLastUpdate, getLastQuoteTimestamp, nextLastUpdate, type LastUpdateState } from '@/utils/statusBar';

interface StatusBarProps {
    isConnected: boolean;
    isAuthenticated: boolean;
}

export default function StatusBar({ isConnected, isAuthenticated }: StatusBarProps) {
    // Last real *quote* data timestamp for the symbol on screen — scoped to
    // data_type==='quote' AND (symbol===selected OR symbol==='*') so a
    // background history/fundamentals sweep for this or another symbol can't
    // bump this clock (bd:ui-honesty-2026-09 F3 r2 — Chris Medium #1,
    // `03b-bella-spec-r2-F3.md`). `null` until a qualifying message arrives
    // for the currently-selected symbol this session.
    const dataReadyPayload = useAppStore((s) => s.dataReadyPayload);
    const selectedSymbol = useAppStore((s) => s.selectedStock.sym);

    // `dataReadyPayload` is a single store slot overwritten on EVERY
    // data_ready message (useWebSocket.ts:77), including non-qualifying ones
    // (history/fundamentals sweeps). Deriving the displayed timestamp fresh
    // from that slot on every render would let a later non-qualifying
    // message wipe an already-earned timestamp back to "—" — a regression
    // Quinn's F3 r3 review pinned (AC3/AC4: a non-qualifying message must
    // leave the prior value UNCHANGED). So we remember the last qualifying
    // value here, in component-local state keyed to the selected symbol, via
    // the pure `nextLastUpdate` reducer in utils/statusBar.ts — no new store
    // field, no change to setDataReadyPayload/useWebSocket.ts (Bella r2 hard
    // constraint), so useChartData.ts's own consumption of dataReadyPayload
    // is untouched.
    //
    // The initializer reads the CURRENT store value directly (not via an
    // effect), so a qualifying message already sitting in the store at mount
    // time is picked up on the very first render — no missed-first-message
    // gap.
    const [remembered, setRemembered] = useState<LastUpdateState>(() => ({
        symbol: selectedSymbol,
        timestamp: getLastQuoteTimestamp(dataReadyPayload, selectedSymbol),
    }));

    // "Adjust state during render" (React-documented pattern, not useEffect):
    // a useEffect here would land one render late, so a qualifying message
    // that arrives in the same tick as a symbol switch could be missed for a
    // frame, and a naive effect keyed on `dataReadyPayload` alone would also
    // re-fire (and could loop) on every non-qualifying message. Comparing
    // during render and only calling setState when the reducer's output
    // actually differs keeps this a no-op re-render for non-qualifying
    // messages (AC3/AC4) while still updating same-frame for qualifying ones
    // and for symbol switches (AC5).
    const next = nextLastUpdate(remembered, dataReadyPayload, selectedSymbol);
    if (next.symbol !== remembered.symbol || next.timestamp !== remembered.timestamp) {
        setRemembered(next);
    }
    const lastUpdateKey = next.timestamp;

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
                        <span className="text-xs" style={{ color: 'var(--color-text-sub)' }}>
                            ราคา {selectedSymbol} อัปเดตล่าสุด: {formatLastUpdate(lastUpdateKey, Date.now())}
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
