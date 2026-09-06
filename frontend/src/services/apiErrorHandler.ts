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
    config?: {
        url?: string;
        /**
         * bd:shotockviz-tjh — per-request opt-out from the global
         * clear-session-on-401 behaviour below. See the DECISION comment
         * on `handleApiError`'s 401 branch for the rule and why this is a
         * flag on the request, not a URL/path table like `silentPaths`.
         */
        skipAuthClearOn401?: boolean;
    };
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
    //
    // bd:shotockviz-tjh — DECISION: any 401 clearing the session on ANY
    // request (including ones the current page doesn't depend on, e.g. a
    // background hydrate GET that already degrades to a cached/default
    // value and swallows its own error) was a side effect of this handler
    // sitting above every request, not a choice anyone made. Chosen rule:
    // opt IN requests that are genuinely decorative via
    // `config.skipAuthClearOn401 = true`, rather than requiring every
    // background read to pre-check auth state before firing. Rejected
    // alternative ("every background read auth-gated before it fires")
    // would mean re-plumbing isAuthenticated into every one of the ~10
    // background reads across the app (quotes, history, fundamentals,
    // news, search, sr-levels, settings/trader, ...) instead of the one or
    // two call sites that are actually decorative — more surface area for
    // the exact "side effect nobody chose" failure mode this bd is about.
    // Fail-safe: a request that never mentions the flag (undefined) OR
    // sets it to `false` gets today's behaviour unchanged — it clears the
    // session on a real 401. Only an explicit `true` narrows this ONE
    // branch; a flagged request still toasts normally on any other status
    // (e.g. 500) — see apiErrorHandler.test.ts's dedicated test for that.
    if (status === 401) {
        if (error.config?.skipAuthClearOn401) {
            return;
        }
        // bd:shotockviz-2qw — mark the rejection HERE, in the branch that
        // actually clears the session, so `didClearAuthSession()` below can
        // never drift from the condition that caused it. A component's own
        // `.catch` still runs after this and would otherwise render "save
        // failed, try again" on top of a logout — inviting the trader to
        // retry a form they no longer have a session for. Set before the
        // store call, so the mark survives even if that throws.
        markAuthSessionCleared(error);
        deps.authStore.getState().handleUnauthorizedResponse();
        return;
    }
    if (status === 404) {
        return;
    }

    deps.showToast(extractErrorMessage(error), { id: `api-err-${status}` });
}


// ─── bd:shotockviz-2qw — "was this rejection a logout?" ─────────────────────
//
// Two signals fire on a 401 mid-save: this handler clears the session
// (deliberate — bd:shotockviz-tjh left both PATCH save actions unflagged
// precisely so a genuinely expired session still logs you out), and the
// calling component's own `.catch` renders its inline save error. Each is
// correct alone; together they log the trader out while telling them to try
// saving again.
//
// The fix is NOT to stop clearing the session on 401 — that is the tjh
// decision and it stands. It is to let a component tell the two failures
// apart, so it can stay quiet about a save that failed because the session
// ended rather than because the save was rejected.
//
// A flag stamped by the branch itself, rather than a component re-deriving
// `status === 401 && !config.skipAuthClearOn401`: re-deriving it puts the
// same condition in three places, and this codebase has repeatedly paid for
// exactly that (five hand-rolled Telegram senders, five fund-NAV dicts, two
// market-hours models). A request that opted out with `skipAuthClearOn401`
// is NOT marked, so its 401 is a plain failure the component should still
// report — which is the right answer, since no session was cleared.

interface AuthClearedMarker {
    __authSessionCleared?: boolean;
}

function markAuthSessionCleared(error: unknown): void {
    if (error && typeof error === 'object') {
        (error as AuthClearedMarker).__authSessionCleared = true;
    }
}

/**
 * True when THIS rejection is the one that cleared the auth session, i.e. the
 * user has just been logged out and any "save failed" message the caller is
 * about to show would be both redundant and misleading.
 */
export function didClearAuthSession(error: unknown): boolean {
    return Boolean(
        error && typeof error === 'object' && (error as AuthClearedMarker).__authSessionCleared,
    );
}
