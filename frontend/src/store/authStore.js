import { create } from 'zustand';
import api from '@/services/api';

/**
 * Safe localStorage helpers — no-op on the server (SSR / TanStack Start).
 * Prevents "localStorage is not defined" hydration errors.
 */
const ls = {
    get: (key) => (typeof window !== 'undefined' ? localStorage.getItem(key) : null),
    set: (key, val) => { if (typeof window !== 'undefined') localStorage.setItem(key, val); },
    del: (key) => { if (typeof window !== 'undefined') localStorage.removeItem(key); },
};

/**
 * Parse JWT expiry without a library.
 * Returns seconds-until-expiry, or 0 if invalid/expired.
 */
function jwtSecondsLeft(token) {
    try {
        const payload = JSON.parse(atob(token.split('.')[1]));
        return Math.max(0, payload.exp - Math.floor(Date.now() / 1000));
    } catch {
        return 0;
    }
}

// Singleton refresh timer so we never schedule more than one
let _refreshTimer = null;

function clearRefreshTimer() {
    if (_refreshTimer) { clearTimeout(_refreshTimer); _refreshTimer = null; }
}

/**
 * Schedule a proactive token refresh 2 minutes before expiry.
 * Falls back gracefully — if refresh fails the reactive 401 interceptor still works.
 */
function scheduleRefresh(token, refreshFn) {
    clearRefreshTimer();
    const secsLeft = jwtSecondsLeft(token);
    if (secsLeft <= 0) return;
    // Refresh 2 min before expiry, but no sooner than 30 s from now
    const delay = Math.max(30, secsLeft - 120) * 1000;
    _refreshTimer = setTimeout(refreshFn, delay);
}

const useAuthStore = create((set, get) => ({
    user: null,
    isAuthenticated: false,
    isLoading: true,
    // ── token exposed in state so useWebSocket can subscribe ─────────────────
    token: ls.get('access_token'),

    // ── Silent proactive token refresh (uses the backend refresh endpoint) ───
    silentRefresh: async () => {
        const rt = ls.get('refresh_token');
        if (!rt) return;
        try {
            const { data } = await api.post('/auth/refresh', { refresh_token: rt });
            ls.set('access_token',  data.access_token);
            ls.set('refresh_token', data.refresh_token);
            set({ token: data.access_token });
            scheduleRefresh(data.access_token, get().silentRefresh);
        } catch {
            // Refresh failed — the reactive 401 interceptor will handle it
        }
    },

    // ── Google OAuth login ────────────────────────────────────────────────────
    googleLogin: async (credential) => {
        const { data } = await api.post('/auth/google', { credential });
        ls.set('access_token',  data.access_token);
        ls.set('refresh_token', data.refresh_token);
        const me = await api.get('/auth/me');
        set({ token: data.access_token, user: me.data, isAuthenticated: true, isLoading: false });
        scheduleRefresh(data.access_token, get().silentRefresh);
        return me.data;
    },

    // ── Register (email only) ─────────────────────────────────────────────────
    register: async (email, password, displayName) => {
        await api.post('/auth/register', {
            email,
            password,
            display_name: displayName,
        });
    },

    // ── Logout ────────────────────────────────────────────────────────────────
    logout: async () => {
        clearRefreshTimer();
        const rt = ls.get('refresh_token');
        if (rt) {
            try { await api.post('/auth/logout', { refresh_token: rt }); } catch { /* ignore */ }
        }
        ls.del('access_token');
        ls.del('refresh_token');
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
            scheduleRefresh(token, get().silentRefresh);
        } catch (err) {
            if (err?.response?.status === 401) {
                // Access token invalid. The refresh interceptor already tried
                // to use the refresh token:
                //   • If refresh succeeded → the interceptor retried /auth/me
                //     and we'd be in the success branch above, not here.
                //   • If refresh failed with 401/403 → interceptor cleared
                //     tokens and redirected to /login.
                //   • If refresh failed with a network error → interceptor did
                //     NOT clear tokens (they may still be valid later).
                // So: only clear tokens when there's definitely no refresh token.
                const hasRefresh = !!ls.get('refresh_token');
                if (!hasRefresh) {
                    clearRefreshTimer();
                    ls.del('access_token');
                    set({ token: null, user: null, isAuthenticated: false, isLoading: false });
                } else {
                    // Refresh token exists but network failed — unblock UI,
                    // keep tokens, and retry once more after 30 s.
                    set({ isLoading: false });
                    if (retryCount === 0) {
                        setTimeout(() => get().checkAuth(1), 30_000);
                    }
                }
            } else if (retryCount < 5) {
                // Network error / 502 — backend still starting up
                const delays = [2000, 4000, 6000, 10000, 15000];
                const delay = delays[retryCount] ?? 15000;
                setTimeout(() => get().checkAuth(retryCount + 1), delay);
            } else {
                // Gave up — unblock UI, keep tokens for next page load
                set({ isLoading: false });
            }
        }
    },
}));

export { useAuthStore };
export default useAuthStore;
