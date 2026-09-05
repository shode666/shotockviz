/**
 * bd:features-2026-09 — shared 401-cleanup logic.
 *
 * Split out of authStore.ts so it has ZERO imports (no zustand, no axios,
 * no `@/` path alias) and can run directly under plain `node --test`
 * (no bundler to resolve aliases — same constraint documented in
 * src/hooks/useWebSocket.test.ts / wsDataReady.ts).
 *
 * `checkAuth()` (authStore.ts) and the global response interceptor
 * (services/api.ts) both call `clearAuthSession()` instead of each
 * duplicating the "delete token + flip isAuthenticated false" steps.
 * Dependencies (`removeToken`, `setAuthState`) are injected so this file
 * never touches localStorage or Zustand directly — that keeps it a pure,
 * side-effect-free function to test, while the *callers* own the actual
 * side effects.
 *
 * ADR-007 / CLAUDE.md rule 5 ("NO custom token management on frontend"):
 * this is a passive state flip only — it clears the existing token and
 * marks the session logged-out. It does NOT request, parse, or re-issue
 * any token. Re-authentication is Google One Tap's job (__root.tsx).
 */

export interface ClearedAuthState {
    token: null;
    user: null;
    isAuthenticated: false;
    isLoading: false;
}

export interface AuthCleanupDeps {
    /** Remove the stored access token (e.g. localStorage.removeItem). */
    removeToken: () => void;
    /** Apply the cleared-session patch to the store (e.g. Zustand `set`). */
    setAuthState: (patch: ClearedAuthState) => void;
}

export const CLEARED_AUTH_STATE: ClearedAuthState = {
    token: null,
    user: null,
    isAuthenticated: false,
    isLoading: false,
};

/**
 * Clear the local session: delete the stored token and flip
 * `isAuthenticated` to false. Reused by both `authStore.checkAuth()`'s
 * existing 401 handling and the new global response interceptor
 * (services/api.ts) so the two never drift out of sync.
 */
export function clearAuthSession(deps: AuthCleanupDeps): void {
    deps.removeToken();
    deps.setAuthState(CLEARED_AUTH_STATE);
}

/**
 * bd:features-2026-09 round 2 (Quinn Medium, non-blocking but bundled here) —
 * idempotence guard for `handleUnauthorizedResponse`. Quinn's integration
 * test proved 3 concurrent in-flight 401s each call `clearAuthSession`,
 * causing 3 redundant `set()` calls (and re-renders across ~10 unguarded
 * `useAuthStore()` consumers) instead of 1 — final state was still correct,
 * just wasteful. `handleUnauthorizedResponse` should call this first and
 * skip the cleanup once the session is already cleared.
 */
export function shouldClearSession(isAuthenticated: boolean): boolean {
    return isAuthenticated;
}

/**
 * bd:features-2026-09 round 2 — same extraction treatment applied to
 * `checkAuth()`'s catch-block branching (401 -> clear / network error ->
 * retry-with-backoff / retries exhausted -> give up), for the same reason
 * `handleApiError` was extracted from api.ts: a source-text scan of
 * `authStore.ts`'s catch block can't prove the 401 branch is reachable
 * (e.g. a `false &&` mutation would still pass a text-match test). This
 * pure classifier is invoked for real by `authCleanup.test.ts`, so that
 * class of mutation fails the test instead of passing it.
 */
export type CheckAuthErrorAction = 'clear-session' | 'retry' | 'give-up';

export function classifyCheckAuthError(
    status: number | undefined,
    retryCount: number,
    maxRetries = 5,
): CheckAuthErrorAction {
    if (status === 401) return 'clear-session';
    if (retryCount < maxRetries) return 'retry';
    return 'give-up';
}
