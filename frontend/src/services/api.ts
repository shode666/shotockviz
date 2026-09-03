import axios, { type AxiosError, type AxiosResponse, type InternalAxiosRequestConfig } from 'axios';
import toast from 'react-hot-toast';

// Always use relative path — Vite proxy forwards /api → http://backend:8000
// (VITE_API_URL=http://backend:8000 is not resolvable from the browser)
//
// bd:deps-2026-09 S2 (ADR-001 r3, AC-B2-r3) — baseURL flips /api -> /api/v1
// (no legacy alias, single atomic flip with the backend prefix lift).
// aiService.js's 3 axios call sites explicitly override this instance's
// baseURL per-request (config.baseURL: '/api') to keep hitting the
// unversioned /api/ai/* path (r3-1) — see aiService.js.
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
// management on frontend"). A 401 now falls straight through to the generic
// error interceptor below; authStore.checkAuth() clears the stale token and
// Google One Tap silently re-authenticates.

// Global error handling and toast notifications
// Data endpoints (quotes, history) are silent on failure — chart/panel handles fallback UI
// /search is silent — the sidebar search box shows empty results on failure, no toast needed
const SILENT_PATHS = ['/quote', '/history', '/fundamentals', '/news', '/search', '/auth/me', '/system/ready'];
const isSilentPath = (url = ''): boolean => SILENT_PATHS.some((p) => url.includes(p));

// bd:deps-2026-09 S2 (ADR-002, AC-B4-r3) — single central unwrap point.
// Every /api/v1/* and /api/ai/* JSON response is now enveloped as
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

interface ApiErrorBody {
    detail?: string | Array<{ msg: string }>;
    meta?: { error?: { message?: string } };
}

api.interceptors.response.use(
    (response: AxiosResponse & { meta?: unknown }) => {
        if (_isEnvelope(response.data)) {
            response.meta = response.data.meta;
            response.data = response.data.data;
        }
        return response;
    },
    (error: AxiosError<ApiErrorBody>) => {
        const url = error.config?.url || '';
        const status = error.response?.status;
        const body = error.response?.data;

        // Silently drop data-fetching errors — chart shows stale/mock data instead
        if (isSilentPath(url)) {
            return Promise.reject(error);
        }

        // Timeout — show a brief user-friendly message
        if (error.code === 'ECONNABORTED') {
            toast.error('Request timed out — please try again', { id: 'timeout' });
            return Promise.reject(error);
        }

        // bd:deps-2026-09 S2 (AC-B4-r3) — error body is now the enveloped
        // shape {data: null, meta: {..., error: {message}}}; the old
        // FastAPI-default `detail` (string | validation-error array) no
        // longer appears on /api/v1/* or /api/ai/* (schemas/envelope.py
        // install_error_envelope). Keep the `detail` fallback only for any
        // response that somehow isn't enveloped (defense in depth).
        let msg = error.message || 'API Request Failed';
        if (body?.meta?.error?.message) {
            msg = body.meta.error.message;
        } else if (body?.detail) {
            if (Array.isArray(body.detail)) {
                msg = body.detail.map((e) => e.msg).join(', ');
            } else if (typeof body.detail === 'string') {
                msg = body.detail;
            }
        }

        // 401 is silent here — authStore.checkAuth() clears the token and
        // Google One Tap re-authenticates (ADR-007); 404 for data is silent
        if (status === 401 || status === 404) return Promise.reject(error);

        toast.error(msg, { id: `api-err-${status}` });
        return Promise.reject(error);
    }
);

// Export both default and named for backward compatibility
export { api };
export default api;
