import { useEffect, useState, useRef } from 'react';
import useAuthStore from '@/store/authStore';
import toast from 'react-hot-toast';

export default function useWebSocket() {
    const { token, user } = useAuthStore();
    const [isConnected, setIsConnected] = useState(false);
    const wsRef = useRef(null);
    const reconnectTimeoutRef = useRef(null);
    const reconnectAttemptsRef = useRef(0);

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
            // Determine WS URL based on current protocol
            const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
            // Use same host to pass through Caddy/Vite proxy
            // Backend route is /api/ws/prices (unified endpoint for all subscriptions)
            const wsUrl = `${protocol}//${window.location.host}/api/ws/prices`;

            const ws = new WebSocket(wsUrl);

            ws.onopen = () => {
                setIsConnected(true);
                reconnectAttemptsRef.current = 0; // reset backoff on success
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
                            `${data.data.symbol} Alert Triggered! - ${data.data.condition}`,
                            { duration: 5000, position: 'top-right' }
                        );
                    } else if (data.type === 'price_update') {
                        // Optional: Handle live price updates if pushed via WS
                    }
                } catch (e) {
                    console.error('Failed to parse WS message', e);
                }
            };

            ws.onclose = () => {
                setIsConnected(false);
                // Exponential backoff: 2s, 4s, 8s, 16s, 30s (max)
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
