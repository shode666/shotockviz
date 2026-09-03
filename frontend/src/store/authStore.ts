import { create } from 'zustand';
import api from '@/services/api';

/**
 * Safe localStorage helpers — no-op on the server (SSR / TanStack Start).
 * Prevents "localStorage is not defined" hydration errors.
 */
const ls = {
    get: (key: string): string | null => (typeof window !== 'undefined' ? localStorage.getItem(key) : null),
    set: (key: string, val: string): void => { if (typeof window !== 'undefined') localStorage.setItem(key, val); },
    del: (key: string): void => { if (typeof window !== 'undefined') localStorage.removeItem(key); },
};

export interface AuthUser {
    id: number;
    email: string;
    display_name: string;
    role: string;
    created_at: string;
}

interface AuthState {
    user: AuthUser | null;
    isAuthenticated: boolean;
    isLoading: boolean;
    token: string | null;
    googleLogin: (credential: string) => Promise<AuthUser>;
    logout: () => Promise<void>;
    checkAuth: (retryCount?: number) => Promise<void>;
}

// bd:deps-2026-09 S1 (ADR-007) — removed: JWT-expiry parsing + proactive
// re-issue timer, the proactive silent-reissue action, register(), and
// the secondary long-lived token's localStorage read/write.
// CLAUDE.md rule 5 ("NO custom token management on frontend") is now
// actually true: this store only stores + attaches the issued access JWT
// (Authorization: Bearer, api.js) and lets Google One Tap
// (GoogleOneTapManager, __root.tsx) silently re-authenticate when the
// session ends — no client-side refresh lifecycle.
const useAuthStore = create<AuthState>()((set, get) => ({
    user: null,
    isAuthenticated: false,
    isLoading: true,
    // ── token exposed in state so useWebSocket can subscribe ─────────────────
    token: ls.get('access_token'),

    // ── Google OAuth login ────────────────────────────────────────────────────
    googleLogin: async (credential: string) => {
        const { data } = await api.post('/auth/google', { credential });
        ls.set('access_token', data.access_token);
        const me = await api.get('/auth/me');
        set({ token: data.access_token, user: me.data, isAuthenticated: true, isLoading: false });
        return me.data;
    },

    // ── Logout ────────────────────────────────────────────────────────────────
    logout: async () => {
        // No refresh token to revoke server-side (ADR-007) — local clear only.
        ls.del('access_token');
        set({ token: null, user: null, isAuthenticated: false, isLoading: false });
    },

    // ── Restore session on app start ─────────────────────────────────────────
    // retryCount: backoff retries when backend is still starting up (502 etc.)
    // Backoff: 2s, 4s, 6s, 10s, 15s — covers Docker cold-start (up to ~37s total)
    checkAuth: async (retryCount = 0) => {
        if (typeof window === 'undefined') {
            set({ isLoading: false });
            return;
        }

        const token = ls.get('access_token');
        if (!token) {
            set({ token: null, isLoading: false });
            return;
        }

        try {
            // 15 s timeout — Docker cold-start can take 10-15 s on first request
            const { data } = await api.get('/auth/me', { timeout: 15000 });
            set({ token, user: data, isAuthenticated: true, isLoading: false });
        } catch (err: any) {
            if (err?.response?.status === 401) {
                // Access token invalid/expired — clear it. Google One Tap
                // (GoogleOneTapManager, __root.tsx) picks up from here:
                // isAuthenticated flips false → its `disabled` flag flips
                // false → it silently re-authenticates without a popup.
                ls.del('access_token');
                set({ token: null, user: null, isAuthenticated: false, isLoading: false });
            } else if (retryCount < 5) {
                // Network error / 502 — backend still starting up
                const delays = [2000, 4000, 6000, 10000, 15000];
                const delay = delays[retryCount] ?? 15000;
                setTimeout(() => get().checkAuth(retryCount + 1), delay);
            } else {
                // Gave up — unblock UI, keep token for next page load
                set({ isLoading: false });
            }
        }
    },
}));

export { useAuthStore };
export default useAuthStore;
