import { useEffect, useState, useRef, useCallback } from 'react';
import useAuthStore from '@/store/authStore';
import useAppStore from '@/store/appStore';
import toast from 'react-hot-toast';
import { shouldBumpDataVersion } from './wsDataReady';

/**
 * WebSocket hook for real-time updates.
 *
 * Handles 3 message types from backend:
 *   - 'alert_triggered' → show toast notification
 *   - 'price_update'    → update live prices in sidebar
 *   - 'data_ready'      → backend finished fetching external data,
 *                          bump dataVersion so React components re-fetch
 *                          (quote data_type bumps immediately — see
 *                          shouldBumpDataVersion)
 */
export default function useWebSocket() {
    const { token, user } = useAuthStore();
    const setDataReadyPayload = useAppStore(s => s.setDataReadyPayload);
    const [isConnected, setIsConnected] = useState(false);
    const wsRef = useRef(null);
    const reconnectTimeoutRef = useRef(null);
    const reconnectAttemptsRef = useRef(0);

    // Store latest setDataReadyPayload in ref to avoid stale closure
    const setPayloadRef = useRef(setDataReadyPayload);
    setPayloadRef.current = setDataReadyPayload;

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
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            const wsUrl = `${protocol}//${window.location.host}/api/ws/prices`;

            const ws = new WebSocket(wsUrl);

            ws.onopen = () => {
                setIsConnected(true);
                reconnectAttemptsRef.current = 0;
                if (reconnectTimeoutRef.current) {
                    clearTimeout(reconnectTimeoutRef.current);
                    reconnectTimeoutRef.current = null;
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
                        // Live price push from Celery worker
                        // Components can listen to appStore.dataVersion for refresh
                    }
                } catch (e) {
                    console.error('Failed to parse WS message', e);
                }
            };

            ws.onclose = () => {
                setIsConnected(false);
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

    return { isConnected };
}
