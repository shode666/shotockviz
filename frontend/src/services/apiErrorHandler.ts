/**
 * bd:features-2026-09 (round 2 — Chris High finding) — the response
 * interceptor's error-handling logic, extracted out of `api.ts` and taking
 * its dependencies as plain parameters (same DI pattern as
 * `store/authCleanup.ts`), so it can be invoked directly in a test with a
 * constructed error object + a fake auth store/toast — instead of only
 * being provable by a source-text scan.
 *
 * Chris proved the round-1 tests (`authCleanup.test.ts` #4/#5) were a real
 * gap: mutating `api.ts`'s `status === 401` check to `false && status === 401`
 * (making the whole fix a dead branch — the original bug fully returns)
 * still passed all 29 tests, because those tests only grepped source text
 * and never actually invoked the interceptor. `handleApiError()` below is
 * invoked for real by `apiErrorHandler.test.ts` with a spy in place of
 * `authStore.getState().handleUnauthorizedResponse`, so the same class of
 * mutation (dead 401 branch) now fails the test (spy never called).
 *
 * Zero imports (besides types) — importable directly under plain
 * `node --test`, same constraint as authCleanup.ts (no bundler to resolve
 * `@/` aliases or axios/react-hot-toast's own transitive imports).
 */

export interface ApiErrorBody {
    detail?: string | Array<{ msg: string }>;
    meta?: { error?: { message?: string } };
}

/** Minimal shape this module needs from an AxiosError — not the real axios type,
 * so tests can construct one as a plain object without importing axios. */
export interface ApiErrorLike {
    code?: string;
    message?: string;
    config?: { url?: string };
    response?: { status?: number; data?: ApiErrorBody };
}

export interface AuthStoreLike {
    getState: () => { handleUnauthorizedResponse: () => void };
}

export interface ApiErrorHandlerDeps {
    /** URL substrings that should never surface a toast (data endpoints with fallback UI). */
    silentPaths: string[];
    /** Zustand-store-shaped dependency — pass `useAuthStore` in production, a fake `{getState}` in tests. */
    authStore: AuthStoreLike;
    /** Toast side effect, injected so tests don't need react-hot-toast/DOM. */
    showToast: (message: string, opts: { id: string }) => void;
}

export const isSilentPath = (url = '', silentPaths: string[]): boolean =>
    silentPaths.some((p) => url.includes(p));

// bd:deps-2026-09 S2 (AC-B4-r3) — error body is now the enveloped
// shape {data: null, meta: {..., error: {message}}}; the old
// FastAPI-default `detail` (string | validation-error array) no
// longer appears on /api/v1/* (schemas/envelope.py
// install_error_envelope). Keep the `detail` fallback only for any
// response that somehow isn't enveloped (defense in depth).
export function extractErrorMessage(error: ApiErrorLike): string {
    const body = error.response?.data;
    if (body?.meta?.error?.message) {
        return body.meta.error.message;
    }
    if (body?.detail) {
        if (Array.isArray(body.detail)) {
            return body.detail.map((e) => e.msg).join(', ');
        }
        if (typeof body.detail === 'string') {
            return body.detail;
        }
    }
    return error.message || 'API Request Failed';
}

/**
 * The response interceptor's rejection-handler logic. Called for every
 * failed `/api/v1/*` request. Returns nothing — callers (api.ts) still do
 * `return Promise.reject(error)` themselves; this function's job is only
 * the side effects (toast / auth-state flip), so it stays trivially
 * testable (no Promise machinery to await in tests).
 */
export function handleApiError(error: ApiErrorLike, deps: ApiErrorHandlerDeps): void {
    const url = error.config?.url || '';
    const status = error.response?.status;

    // Silently drop data-fetching errors — chart shows stale/mock data instead
    if (isSilentPath(url, deps.silentPaths)) {
        return;
    }

    // Timeout — show a brief user-friendly message
    if (error.code === 'ECONNABORTED') {
        deps.showToast('Request timed out — please try again', { id: 'timeout' });
        return;
    }

    // bd:features-2026-09 — 401 is silent here; flip local auth state
    // (reusing authStore's existing 401-cleanup, no duplicated logic, no
    // token refresh — ADR-007) so Google One Tap re-authenticates
    // immediately instead of waiting for a reload. 404 for data is silent.
    if (status === 401) {
        deps.authStore.getState().handleUnauthorizedResponse();
        return;
    }
    if (status === 404) {
        return;
    }

    deps.showToast(extractErrorMessage(error), { id: `api-err-${status}` });
}
