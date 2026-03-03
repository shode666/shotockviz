import { create } from 'zustand';

/**
 * SSR-safe browser helpers.
 * TanStack Start renders components on the server; localStorage / document are
 * not available there.  All accesses must be guarded.
 */
const isBrowser = typeof window !== 'undefined';

const useAppStore = create((set) => ({
    // ── Theme ─────────────────────────────────────────────────────────────────
    // Default to 'dark'; initTheme() corrects it on the client from localStorage.
    theme: 'dark',
    darkMode: true,

    toggleTheme: () =>
        set((s) => {
            const next = s.theme === 'dark' ? 'light' : 'dark';
            if (isBrowser) {
                document.documentElement.setAttribute('data-theme', next);
                localStorage.setItem('theme', next);
            }
            return { theme: next, darkMode: next === 'dark' };
        }),

    /**
     * Call once in a client-side useEffect to restore the saved theme.
     * No-op on the server.
     */
    initTheme: () => {
        if (!isBrowser) return;
        const saved = localStorage.getItem('theme') || 'dark';
        document.documentElement.setAttribute('data-theme', saved);
        set({ theme: saved, darkMode: saved === 'dark' });
    },

    // ── Active screen (kept for compat; routing handles page selection) ───────
    screen: 'chart',
    setScreen: (screen) => set({ screen }),

    // ── Selected stock (default shown on first load) ──────────────────────────
    selectedStock: {
        sym:   'NVDA',
        name:  'NVIDIA',
        price: null,
        chg:   null,
        pct:   null,
        up:    true,
    },
    setSelectedStock: (stock) => set({ selectedStock: stock }),

    // ── Search modal open/close ───────────────────────────────────────────────
    searchOpen: false,
    setSearchOpen: (open) => set({ searchOpen: open }),

    // ── Backend readiness / data freshness ───────────────────────────────────
    // Incremented whenever the backend cache becomes ready after startup.
    // Components include this in useEffect deps to auto-refresh stale data.
    dataVersion: 0,
    bumpDataVersion: () => set((s) => ({ dataVersion: s.dataVersion + 1 })),

    // ── WebSocket data_ready payload ──────────────────────────────────────────
    // Stores the latest data_ready message from the WebSocket.
    // Each set creates a new object reference so React/Zustand detects the change.
    // Shape: { type, data_type, symbol, timeframe?, _key: timestamp }
    dataReadyPayload: null,
    setDataReadyPayload: (payload) =>
        set({ dataReadyPayload: { ...payload, _key: Date.now() } }),
}));

export { useAppStore };
export default useAppStore;
