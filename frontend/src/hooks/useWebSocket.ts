import { useEffect, useState, useRef, useCallback } from 'react';
import useAuthStore from '@/store/authStore';
import useAppStore from '@/store/appStore';
import toast from 'react-hot-toast';
import { shouldBumpDataVersion } from './wsDataReady';
import { buildWsUrl } from '@/utils/wsUrl';

/**
 * WebSocket hook for real-time updates.
 *
 * Handles message types from backend:
 *   - 'alert_triggered' → show toast notification
 *   - 'data_ready'      → backend finished fetching external data,
 *                          bump dataVersion so React components re-fetch
 *                          (quote data_type bumps immediately — see
 *                          shouldBumpDataVersion); also stamps
 *                          appStore.dataReadyPayload (consumed by
 *                          useChartData; StatusBar has its own polled path
 *                          since bd:shotockviz-09j).
 *   - 'price_update'    → per-symbol quote push, only delivered for
 *                         symbols this socket subscribed to (see below).
 *                         Logged for observability only — the 60s REST poll
 *                         in usePriceUpdates remains the source of truth for
 *                         displayed prices. Tara (bd:shotockviz-foc): this
 *                         trader is not latency-sensitive, so a polled price
 *                         and a pushed price are the same trade for him; the
 *                         value of subscribing is honesty/closing the CQRS
 *                         loop, not speed. Wiring price_update into UI state
 *                         is a separate, larger change and out of this bd's
 *                         scope.
 *
 * Subscription model (bd:shotockviz-foc):
 *   The backend's ConnectionManager (`main.py`) only forwards `price_update`
 *   to sockets that previously sent `{"action":"subscribe","symbol":...}`,
 *   and it forgets all subscriptions when a socket disconnects
 *   (`ConnectionManager.subscriptions` is keyed by the WebSocket instance —
 *   `main.py:63-64`, `main.py:80` `subscriptions.pop(ws, None)`). So this
 *   hook:
 *     - subscribes to the symbol on screen (`appStore.selectedStock.sym`)
 *       every time a connection is (re)established — including after the
 *       exponential-backoff auto-reconnect below — because server-side
 *       state does not survive a drop;
 *     - unsubscribes the old symbol and subscribes the new one when the
 *       user switches symbols on an already-open socket.
 *
 *   Scope decision: subscribe only to the on-screen symbol, not the whole
 *   sidebar watchlist. The watchlist already gets fresh prices from its own
 *   independent 60s poll (`usePriceUpdates` in Sidebar.tsx), and there is no
 *   shared store of watchlist symbols this hook could read today — Sidebar
 *   keeps that list in local component state. Lifting it into a shared
 *   store to also subscribe every watchlist symbol over WS would be a
 *   materially bigger change for a value Tara already scored as "honesty,
 *   not speed" (the 60s poll is equivalent at this trader's horizon).
 */
export default function useWebSocket() {
    const { token, user } = useAuthStore();
    const setDataReadyPayload = useAppStore(s => s.setDataReadyPayload);
    const selectedSymbol = useAppStore(s => s.selectedStock.sym);
    const [isConnected, setIsConnected] = useState(false);
    const wsRef = useRef<WebSocket | null>(null);
    const reconnectTimeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const reconnectAttemptsRef = useRef(0);

    // Store latest setDataReadyPayload in ref to avoid stale closure
    const setPayloadRef = useRef(setDataReadyPayload);
    setPayloadRef.current = setDataReadyPayload;

    // Latest on-screen symbol, read from `onopen` (which lives inside
    // `connect()`, only re-created when token/user change — not on every
    // symbol switch) and from the reconnect/backoff path.
    const symbolRef = useRef(selectedSymbol);
    // What the server currently believes this socket is subscribed to (or
    // null if nothing is subscribed / the socket isn't open yet).
    const subscribedSymbolRef = useRef<string | null>(null);

    useEffect(() => {
        if (!token || !user?.id) {
            if (wsRef.current) {
                wsRef.current.close();
                wsRef.current = null;
            }
            setIsConnected(false);
            return;
        }

        const connect = () => {
            // bd:shotockviz-pls — the backend now authenticates the WS
            // handshake; pass the same access token api.js already uses
            // for REST. This hook is gated on `token` above, so it never
            // tries to connect logged-out.
            const wsUrl = buildWsUrl(window.location.protocol, window.location.host, token);

            const ws = new WebSocket(wsUrl);

            ws.onopen = () => {
                setIsConnected(true);
                reconnectAttemptsRef.current = 0;
                if (reconnectTimeoutRef.current) {
                    clearTimeout(reconnectTimeoutRef.current);
                    reconnectTimeoutRef.current = null;
                }
                // The server has no memory of this client — (re)subscribe to
                // whatever is on screen right now, not whatever it was when
                // the previous socket dropped.
                subscribedSymbolRef.current = null;
                if (symbolRef.current) {
                    ws.send(JSON.stringify({ action: 'subscribe', symbol: symbolRef.current }));
                    subscribedSymbolRef.current = symbolRef.current;
                }
            };

            ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);

                    if (data.type === 'alert_triggered') {
                        toast.success(
                            `${data.data?.symbol ?? data.symbol} Alert Triggered!`,
                            { duration: 5000, position: 'top-right' }
                        );
                    } else if (data.type === 'data_ready') {
                        // Backend finished fetching external data → store payload so
                        // consumers (useChartData) can decide whether to re-fetch.
                        // data_type: "quote", "history", "fundamentals", "dashboard"
                        // symbol: specific ticker or "*" (broadcast to all)
                        // timeframe: present only for history data_type
                        console.debug('[WS] data_ready:', data.data_type, data.symbol, data.timeframe);
                        if (setPayloadRef.current) {
                            setPayloadRef.current(data);
                        }
                        // Quote data is what the sidebar/watchlist poll (usePriceUpdates)
                        // cares about — bump immediately instead of waiting up to 60s.
                        if (shouldBumpDataVersion(data)) {
                            useAppStore.getState().bumpDataVersion();
                        }
                    } else if (data.type === 'price_update') {
                        // bd:shotockviz-foc — reachable now that this hook sends a
                        // subscribe frame (see docstring). Observability only.
                        console.debug('[WS] price_update:', data.symbol, data.price, data.ts);
                    }
                } catch (e) {
                    console.error('Failed to parse WS message', e);
                }
            };

            ws.onclose = () => {
                setIsConnected(false);
                subscribedSymbolRef.current = null;
                const delay = Math.min(2000 * Math.pow(2, reconnectAttemptsRef.current), 30_000);
                reconnectAttemptsRef.current += 1;
                reconnectTimeoutRef.current = setTimeout(connect, delay);
            };

            ws.onerror = (err) => {
                console.error('WebSocket Error:', err);
                ws.close();
            };

            wsRef.current = ws;
        };

        connect();

        return () => {
            if (reconnectTimeoutRef.current) clearTimeout(reconnectTimeoutRef.current);
            if (wsRef.current) wsRef.current.close();
        };
    }, [token, user?.id]);

    // Switch subscription when the on-screen symbol changes on an
    // already-open socket. Initial subscribe for a fresh/reconnected socket
    // is handled in `onopen` above via `symbolRef`, which this effect keeps
    // current even while disconnected.
    useEffect(() => {
        symbolRef.current = selectedSymbol;

        const ws = wsRef.current;
        if (!ws || ws.readyState !== WebSocket.OPEN) return;

        const current = subscribedSymbolRef.current;
        if (current === selectedSymbol) return;

        if (current) ws.send(JSON.stringify({ action: 'unsubscribe', symbol: current }));
        if (selectedSymbol) ws.send(JSON.stringify({ action: 'subscribe', symbol: selectedSymbol }));
        subscribedSymbolRef.current = selectedSymbol;
    }, [selectedSymbol]);

    return { isConnected };
}
