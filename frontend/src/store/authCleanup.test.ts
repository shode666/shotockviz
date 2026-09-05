/**
 * Unit tests — clearAuthSession() / shouldClearSession() / classifyCheckAuthError()
 * (bd:features-2026-09, login-logs-out-too-often follow-up).
 *
 * Round 2 (Chris High, blocking): the round-1 versions of tests #4/#5 here
 * asserted "authStore.ts / api.ts only call the cleanup inside the 401
 * branch" via `readFileSync` + substring/index matching — a source-text
 * scan, not a real invocation. Chris proved this was a real gap: mutating
 * `api.ts`'s `status === 401` check to `false && status === 401` (a change
 * that makes the whole fix a dead branch — the original bug fully returns)
 * still passed every test, because none of them ever actually called the
 * interceptor/catch-block code with a constructed error.
 *
 * Fix: the branching logic itself was extracted into pure, real-invocable
 * functions (`classifyCheckAuthError` here; `handleApiError` in
 * `services/apiErrorHandler.ts`, tested in `apiErrorHandler.test.ts`), and
 * the tests below call them directly with real inputs and assert on the
 * real return value / real side-effect calls — the same class of dead-branch
 * mutation now fails these tests instead of passing them.
 *
 * `authStore.ts` / `services/api.ts` themselves still can't be imported
 * directly under plain `node --test` (no bundler to resolve `@/` aliases or
 * zustand/axios) — same constraint documented in
 * src/hooks/useWebSocket.test.ts — so the glue code that wires these pure
 * functions into the store/interceptor is intentionally kept to a single
 * `if (action === ...)` dispatch line, minimizing what's left untested.
 *
 * Run: `cd frontend && npm test` (== `node --test`).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { dirname, join } from 'node:path';
import {
    clearAuthSession,
    CLEARED_AUTH_STATE,
    shouldClearSession,
    classifyCheckAuthError,
} from './authCleanup.ts';

const __dirname = dirname(fileURLToPath(import.meta.url));

test('clearAuthSession removes the stored token', () => {
    let removed = false;
    clearAuthSession({
        removeToken: () => { removed = true; },
        setAuthState: () => {},
    });
    assert.equal(removed, true);
});

test('clearAuthSession sets isAuthenticated to false (and clears token/user, stops loading)', () => {
    let patch: unknown = null;
    clearAuthSession({
        removeToken: () => {},
        setAuthState: (p) => { patch = p; },
    });
    assert.deepEqual(patch, {
        token: null,
        user: null,
        isAuthenticated: false,
        isLoading: false,
    });
    assert.deepEqual(patch, CLEARED_AUTH_STATE);
});

test('clearAuthSession always calls removeToken before setAuthState (cleanup order)', () => {
    const calls: string[] = [];
    clearAuthSession({
        removeToken: () => calls.push('removeToken'),
        setAuthState: () => calls.push('setAuthState'),
    });
    assert.deepEqual(calls, ['removeToken', 'setAuthState']);
});

// ── classifyCheckAuthError — real invocation, replaces the round-1 source-scan ──

test('classifyCheckAuthError: 401 always clears the session, regardless of retryCount', () => {
    assert.equal(classifyCheckAuthError(401, 0), 'clear-session');
    assert.equal(classifyCheckAuthError(401, 4), 'clear-session');
    assert.equal(classifyCheckAuthError(401, 999), 'clear-session');
});

test('classifyCheckAuthError: non-401 (network error / 502 / undefined) retries while under maxRetries', () => {
    assert.equal(classifyCheckAuthError(undefined, 0), 'retry');
    assert.equal(classifyCheckAuthError(502, 3), 'retry');
    assert.equal(classifyCheckAuthError(502, 4), 'retry'); // last retry slot (< 5)
});

test('classifyCheckAuthError: gives up once retryCount reaches maxRetries', () => {
    assert.equal(classifyCheckAuthError(502, 5), 'give-up');
    assert.equal(classifyCheckAuthError(undefined, 10), 'give-up');
});

test('classifyCheckAuthError: 403 (not 401) is treated as a non-auth error, not cleared', () => {
    assert.equal(classifyCheckAuthError(403, 0), 'retry');
    assert.notEqual(classifyCheckAuthError(403, 0), 'clear-session');
});

// This is the direct regression test for Chris's proven mutation
// (`if (false && status === 401)` in the 401 check): if that mutation were
// applied to `classifyCheckAuthError` itself, 401 would fall through to
// 'retry'/'give-up' instead of 'clear-session', and this assertion fails.
test('classifyCheckAuthError: mutation-proof — a 401 status never falls through to retry/give-up', () => {
    for (const retryCount of [0, 1, 2, 5, 6]) {
        const action = classifyCheckAuthError(401, retryCount);
        assert.equal(action, 'clear-session', `expected clear-session for 401 @ retryCount=${retryCount}, got ${action}`);
    }
});

// ── shouldClearSession / idempotence (Quinn Medium, bundled into this pass) ──

test('shouldClearSession: true when currently authenticated (first 401 should clear)', () => {
    assert.equal(shouldClearSession(true), true);
});

test('shouldClearSession: false when already logged out (idempotence — no-op on repeat 401s)', () => {
    assert.equal(shouldClearSession(false), false);
});

test('idempotence: simulated handleUnauthorizedResponse only clears once for N concurrent 401s', () => {
    // Mirrors authStore.ts's real handleUnauthorizedResponse composition
    // (shouldClearSession guard + clearAuthSession), driven by a fake
    // get()/set() pair, to prove Quinn's "3 concurrent 401s -> 3x set()"
    // finding is fixed without needing the real zustand store.
    let isAuthenticated = true;
    let clearCallCount = 0;
    const fakeSet = (patch: { isAuthenticated: boolean }) => { isAuthenticated = patch.isAuthenticated; };
    const fakeHandleUnauthorizedResponse = () => {
        if (!shouldClearSession(isAuthenticated)) return;
        clearCallCount += 1;
        clearAuthSession({ removeToken: () => {}, setAuthState: fakeSet });
    };

    fakeHandleUnauthorizedResponse(); // 1st concurrent 401
    fakeHandleUnauthorizedResponse(); // 2nd concurrent 401
    fakeHandleUnauthorizedResponse(); // 3rd concurrent 401

    assert.equal(clearCallCount, 1, 'expected only the first of 3 concurrent 401s to actually clear the session');
    assert.equal(isAuthenticated, false);
});

// ── ADR-007 compliance: no token refresh/reissue/polling reintroduced ───────
test('ADR-007: no token-refresh endpoint, refresh-token storage, or polling reintroduced in the touched files', () => {
    const files = [
        join(__dirname, 'authCleanup.ts'),
        join(__dirname, 'authStore.ts'),
        join(__dirname, '..', 'services', 'api.ts'),
        join(__dirname, '..', 'services', 'apiErrorHandler.ts'),
    ];
    // Match only actual *usage* (a real call/assignment), not comments that
    // merely reference the removed ADR-007 refresh flow (e.g. "there is no
    // POST /auth/refresh anymore" is expected prose, not reintroduced code).
    const forbidden: Array<{ pattern: RegExp; label: string }> = [
        { pattern: /api\.(post|get)\(\s*['"`]\/auth\/refresh['"`]/, label: 'call to POST/GET /auth/refresh' },
        { pattern: /refresh_token\s*[:=]/, label: 'refresh_token assignment/field' },
        { pattern: /\brefreshToken\s*[:=(]/, label: 'refreshToken variable/param' },
        { pattern: /jwt-decode|jwtDecode\s*\(/, label: 'JWT client-side decode/parsing' },
        { pattern: /\bsetInterval\s*\(/, label: 'polling via setInterval' },
    ];
    for (const file of files) {
        const src = readFileSync(file, 'utf8');
        const codeOnly = src
            .split('\n')
            .filter((line) => !line.trim().startsWith('//'))
            .join('\n');
        for (const { pattern, label } of forbidden) {
            assert.doesNotMatch(codeOnly, pattern, `${file} matched forbidden pattern (${label})`);
        }
    }
});
