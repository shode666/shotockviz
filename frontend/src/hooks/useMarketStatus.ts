/**
 * bd:shotockviz-pt8 — Dashboard and Navbar each ran their own
 * `useState(getSetStatus) + useState(getUsStatus) + setInterval(60s)`
 * polling wrapper. ADR-UH-004 already put the *logic* in one place
 * (utils/marketStatus.ts, client-side, no backend endpoint — decision kept
 * intact here); what was still duplicated was the polling wrapper itself.
 * One shared hook, one interval, one source both consumers subscribe to —
 * they cannot drift apart again the way F4 did.
 */
import { useState, useEffect } from 'react';
import { getBothMarketStatus, type BothMarketStatus } from '@/utils/marketStatus';

export function useMarketStatus(): BothMarketStatus {
    const [status, setStatus] = useState<BothMarketStatus>(getBothMarketStatus);

    useEffect(() => {
        const t = setInterval(() => setStatus(getBothMarketStatus()), 60_000);
        return () => clearInterval(t);
    }, []);

    return status;
}

export default useMarketStatus;
