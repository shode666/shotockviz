import axios, { type AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios';
import toast from 'react-hot-toast';
import { useAuthStore } from '@/store/authStore';
import { handleApiError, type ApiErrorBody } from './apiErrorHandler';

// Always use relative path — Vite proxy forwards /api → http://backend:8000
// (VITE_API_URL=http://backend:8000 is not resolvable from the browser)
//
// bd:deps-2026-09 S2 (ADR-001 r3, AC-B2-r3) — baseURL flips /api -> /api/v1
// (no legacy alias, single atomic flip with the backend prefix lift).
//
// timeout: 12 s — prevents connection-starvation when stock-data requests
// (PTT.BK, CPALL.BK) hang waiting for Yahoo/Stooq fallbacks.
// Chrome allows only 6 concurrent connections per host; if all 6 are held
// by pending quote requests, the login POST gets queued indefinitely.
const api = axios.create({
    baseURL: '/api/v1',
    headers: { 'Content-Type': 'application/json' },
    timeout: 12_000,
});

// Attach JWT to every request
api.interceptors.request.use((config: InternalAxiosRequestConfig) => {
    const token = localStorage.getItem('access_token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

// bd:deps-2026-09 S1 (ADR-007) — the 401 auto-refresh interceptor was removed
// (there is no POST /auth/refresh anymore; CLAUDE.md rule 5 "NO custom token
// management on frontend"). This stays true below: on a 401 we only flip
// local state (delete the stale token, isAuthenticated -> false) — we never
// request, parse, or re-issue a token from here. No polling, no timer.
//
// bd:features-2026-09 — this was previously *only* handled by
// authStore.checkAuth() on app mount, which runs once. If the 8h JWT
// (backend/core/config.py) expires mid-session, every other endpoint starts
// returning 401 but isAuthenticated never flipped false until a page
// reload — so Google One Tap (disabled: isLoading || isAuthenticated,
// __root.tsx) never re-fired. The response-error handling below (extracted
// to services/apiErrorHandler.ts::handleApiError, DI'd with `useAuthStore`)
// reuses authStore's existing 401-cleanup (clearAuthSession, authCleanup.ts)
// on ANY 401 response so One Tap unblocks immediately instead of waiting
// for the next reload.

// Global error handling and toast notifications
// Data endpoints (quotes, history) are silent on failure — chart/panel handles fallback UI
// /search is silent — the sidebar search box shows empty results on failure, no toast needed
const SILENT_PATHS = ['/quote', '/history', '/fundamentals', '/news', '/search', '/auth/me', '/system/ready', '/sr-levels'];

// bd:deps-2026-09 S2 (ADR-002, AC-B4-r3) — single central unwrap point.
// Every /api/v1/* JSON response is now enveloped as
// {data, meta} (schemas/envelope.py). Unwrap here so the ~40 existing
// call sites across services/*.js keep reading `response.data.<field>`
// unchanged (they get the inner `data`, not the envelope). `meta` is not
// discarded — attached as `response.meta` for the rare caller that wants
// data_status/cached_layer/pagination (opt-in, doesn't break anyone).
interface Envelope {
    data: unknown;
    meta: unknown;
}

const _isEnvelope = (body: unknown): body is Envelope =>
    body !== null && typeof body === 'object' && 'data' in body && 'meta' in body;

api.interceptors.response.use(
    (response: AxiosResponse & { meta?: unknown }) => {
        if (_isEnvelope(response.data)) {
            response.meta = response.data.meta;
            response.data = response.data.data;
        }
        return response;
    },
    (error: AxiosError<ApiErrorBody>) => {
        handleApiError(error, {
            silentPaths: SILENT_PATHS,
            authStore: useAuthStore,
            showToast: (message, opts) => toast.error(message, opts),
        });
        return Promise.reject(error);
    }
);

// Export both default and named for backward compatibility
export { api };
export default api;
