/**
 * ClientOnly — renders children only after first client-side mount.
 *
 * Prevents SSR hydration mismatches for components that:
 *  • Use browser APIs (localStorage, window, document)
 *  • Load third-party scripts that inject DOM (e.g. Google OAuth button)
 *  • Have non-deterministic server/client output
 *
 * Usage:
 *   <ClientOnly fallback={<Spinner />}>
 *     <GoogleLogin ... />
 *   </ClientOnly>
 */
import { useState, useEffect } from 'react';
import type { ReactNode } from 'react';

interface Props {
    children: ReactNode;
    /** Optional placeholder shown during SSR / before hydration */
    fallback?: ReactNode;
}

export default function ClientOnly({ children, fallback = null }: Props) {
    const [mounted, setMounted] = useState(false);
    useEffect(() => { setMounted(true); }, []);
    if (!mounted) return <>{fallback}</>;
    return <>{children}</>;
}
