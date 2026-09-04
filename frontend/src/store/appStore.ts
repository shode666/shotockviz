import { create } from 'zustand';

/**
 * SSR-safe browser helpers.
 * TanStack Start renders components on the server; localStorage / document are
 * not available there.  All accesses must be guarded.
 */
const isBrowser = typeof window !== 'undefined';

export interface SelectedStock {
    sym: string;
    name: string;
    price: string | number | null;
    chg: string | number | null;
    pct: string | number | null;
    up: boolean;
}

interface DataReadyPayload {
    [key: string]: unknown;
    _key?: number;
}

interface AppState {
    theme: string;
    darkMode: boolean;
    toggleTheme: () => void;
    setTheme: (theme: string) => void;
    initTheme: () => void;
    screen: string;
    setScreen: (screen: string) => void;
    selectedStock: SelectedStock;
    setSelectedStock: (stock: SelectedStock) => void;
    searchOpen: boolean;
    setSearchOpen: (open: boolean) => void;
    dataVersion: number;
    bumpDataVersion: () => void;
    dataReadyPayload: DataReadyPayload | null;
    setDataReadyPayload: (payload: Record<string, unknown>) => void;
}

const useAppStore = create<AppState>()((set) => ({
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

    // bd:ux-2026-09 user-reported regression investigation — SettingsPage's
    // Dark/Light theme cards both called toggleTheme() regardless of which
    // card was clicked (SettingsPage.tsx:77), so clicking the theme you were
    // ALREADY on silently flipped you to the other one instead of staying
    // put. setTheme() sets explicitly instead of blindly flipping — cards
    // pick a theme, they don't toggle one. toggleTheme() stays as-is for the
    // Navbar sun/moon icon, where flip-current IS the correct semantic.
    setTheme: (theme) =>
        set(() => {
            if (isBrowser) {
                document.documentElement.setAttribute('data-theme', theme);
                localStorage.setItem('theme', theme);
            }
            return { theme, darkMode: theme === 'dark' };
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
