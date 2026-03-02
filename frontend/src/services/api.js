import axios from 'axios';
import toast from 'react-hot-toast';

// Always use relative path — Vite proxy forwards /api → http://backend:8000
// (VITE_API_URL=http://backend:8000 is not resolvable from the browser)
//
// timeout: 12 s — prevents connection-starvation when stock-data requests
// (PTT.BK, CPALL.BK) hang waiting for Yahoo/Stooq fallbacks.
// Chrome allows only 6 concurrent connections per host; if all 6 are held
// by pending quote requests, the login POST gets queued indefinitely.
const api = axios.create({
    baseURL: '/api',
    headers: { 'Content-Type': 'application/json' },
    timeout: 12_000,
});

// Attach JWT to every request
api.interceptors.request.use((config) => {
    const token = localStorage.getItem('access_token');
    if (token) {
        config.headers.Authorization = `Bearer ${token}`;
    }
    return config;
});

// Auto-refresh on 401
api.interceptors.response.use(
    (res) => res,
    async (error) => {
        // Timeout errors should propagate immediately — don't attempt refresh
        if (error.code === 'ECONNABORTED') {
            return Promise.reject(error);
        }

        const original = error.config;
        if (error.response?.status === 401 && !original._retry) {
            original._retry = true;
            const refreshToken = localStorage.getItem('refresh_token');
            if (refreshToken) {
                try {
                    const { data } = await axios.post('/api/auth/refresh', {
                        refresh_token: refreshToken,
                    });
                    localStorage.setItem('access_token', data.access_token);
                    localStorage.setItem('refresh_token', data.refresh_token);
                    original.headers.Authorization = `Bearer ${data.access_token}`;
                    return api(original);
                } catch (refreshErr) {
                    // Only clear tokens if refresh was rejected (401/403),
                    // not on network errors (backend still starting up).
                    if (refreshErr?.response?.status === 401 || refreshErr?.response?.status === 403) {
                        localStorage.removeItem('access_token');
                        localStorage.removeItem('refresh_token');
                        window.location.href = '/login';
                    }
                    return Promise.reject(error);
                }
            }
        }
        return Promise.reject(error);
    },
);

// Global error handling and toast notifications
// Data endpoints (quotes, history) are silent on failure — chart/panel handles fallback UI
// /search is silent — the sidebar search box shows empty results on failure, no toast needed
const SILENT_PATHS = ['/quote', '/history', '/fundamentals', '/news', '/search', '/auth/me', '/system/ready'];
const isSilentPath = (url = '') => SILENT_PATHS.some((p) => url.includes(p));

api.interceptors.response.use(
    (response) => response,
    (error) => {
        const url = error.config?.url || '';
        const status = error.response?.status;

        // Silently drop data-fetching errors — chart shows stale/mock data instead
        if (isSilentPath(url)) {
            return Promise.reject(error);
        }

        // Timeout — show a brief user-friendly message
        if (error.code === 'ECONNABORTED') {
            toast.error('Request timed out — please try again', { id: 'timeout' });
            return Promise.reject(error);
        }

        let msg = error.message || 'API Request Failed';
        if (error.response?.data?.detail) {
            if (Array.isArray(error.response.data.detail)) {
                msg = error.response.data.detail.map(e => e.msg).join(', ');
            } else if (typeof error.response.data.detail === 'string') {
                msg = error.response.data.detail;
            }
        }

        // 401 handled by refresh interceptor above; 404 for data is silent
        if (status === 401 || status === 404) return Promise.reject(error);

        toast.error(msg, { id: `api-err-${status}` });
        return Promise.reject(error);
    }
);

export default api;
