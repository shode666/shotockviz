/**
 * useBackendReady — polls /api/v1/system/ready until the backend cache is warm,
 * then calls bumpDataVersion() so all data-fetching components automatically
 * re-run their queries and display real prices instead of "—".
 *
 * Polling stops as soon as `ready` is true (one-shot).
 */
import { useEffect, useRef } from 'react';
import useAppStore from '@/store/appStore';
import api from '@/services/api';

const POLL_INTERVAL_MS = 3000;
const MAX_ATTEMPTS = 40; // give up after ~2 minutes

export default function useBackendReady() {
    const { bumpDataVersion } = useAppStore();
    const attemptsRef = useRef(0);
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const firedRef = useRef(false);

    useEffect(() => {
        const poll = async () => {
            if (firedRef.current) return;

            attemptsRef.current += 1;
            if (attemptsRef.current > MAX_ATTEMPTS) return;

            try {
                const res = await api.get('/system/ready');
                if (res.data?.ready === true) {
                    firedRef.current = true;
                    bumpDataVersion();   // ← triggers all components to re-fetch
                    return;              // stop polling
                }
            } catch {
                // backend not reachable yet — keep polling
            }

            timerRef.current = setTimeout(poll, POLL_INTERVAL_MS);
        };

        // Small initial delay so the component tree is fully mounted first
        timerRef.current = setTimeout(poll, 1000);

        return () => {
            if (timerRef.current) clearTimeout(timerRef.current);
        };
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, []);
}
