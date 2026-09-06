/**
 * Unit tests — handleApiError() (bd:features-2026-09 round 2, Chris High
 * blocking finding).
 *
 * These are real invocations of the actual interceptor error-handling logic
 * (extracted to apiErrorHandler.ts precisely so it could be called directly
 * here) with a constructed error object and a fake auth-store/toast, per
 * Chris's requested fix (a): "Extract the interceptor's rejection handler
 * into a named, exported function ... taking its dependencies as plain
 * parameters ... so a test can invoke it directly with a constructed error
 * object and a fake store, asserting spy called on 401, not called on
 * 200/403."
 *
 * Regression proof: Chris demonstrated that mutating the real interceptor's
 * `status === 401` check to `false && status === 401` (dead branch — 401s
 * silently fall through, restoring the original "logs out too often" bug)
 * still passed all round-1 tests, because those tests only grepped source
 * text. `handleApiError` is invoked for real below, so the equivalent
 * mutation applied to this file (see "mutation-proof" test) makes the spy
 * assertion fail instead of passing.
 *
 * Zero external imports besides the module under test — importable directly
 * under plain `node --test` (no bundler needed; this file constructs its
 * own fake AuthStoreLike/showToast instead of importing axios/zustand).
 *
 * Run: `cd frontend && npm test` (== `node --test`).
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { handleApiError, isSilentPath, extractErrorMessage, type ApiErrorLike, type AuthStoreLike } from './apiErrorHandler.ts';

const SILENT_PATHS = ['/quote', '/history', '/fundamentals', '/news', '/search', '/auth/me', '/system/ready', '/sr-levels'];

function makeSpyAuthStore() {
    let callCount = 0;
    const authStore: AuthStoreLike = {
        getState: () => ({
            handleUnauthorizedResponse: () => { callCount += 1; },
        }),
    };
    return { authStore, getCallCount: () => callCount };
}

function makeToastSpy() {
    const calls: Array<{ message: string; id: string }> = [];
    const showToast = (message: string, opts: { id: string }) => { calls.push({ message, id: opts.id }); };
    return { showToast, calls };
}

test('handleApiError: 401 on a non-silent path calls authStore.handleUnauthorizedResponse() exactly once and shows no toast', () => {
    const { authStore, getCallCount } = makeSpyAuthStore();
    const { showToast, calls } = makeToastSpy();

    const error: ApiErrorLike = { config: { url: '/watchlist' }, response: { status: 401, data: {} } };
    handleApiError(error, { silentPaths: SILENT_PATHS, authStore, showToast });

    assert.equal(getCallCount(), 1, 'expected handleUnauthorizedResponse to be called exactly once on a real 401');
    assert.equal(calls.length, 0, '401 must stay silent — no toast');
});

test('handleApiError: 200-shaped / non-401 status (e.g. 500) does NOT call handleUnauthorizedResponse', () => {
    const { authStore, getCallCount } = makeSpyAuthStore();
    const { showToast } = makeToastSpy();

    const error: ApiErrorLike = { config: { url: '/portfolio' }, response: { status: 500, data: { detail: 'boom' } } };
    handleApiError(error, { silentPaths: SILENT_PATHS, authStore, showToast });

    assert.equal(getCallCount(), 0, 'a 500 must never trigger the auth-store cleanup');
});

test('handleApiError: 403 does NOT call handleUnauthorizedResponse (only 401 clears the session)', () => {
    const { authStore, getCallCount } = makeSpyAuthStore();
    const { showToast, calls } = makeToastSpy();

    const error: ApiErrorLike = { config: { url: '/admin/users' }, response: { status: 403, data: {} } };
    handleApiError(error, { silentPaths: SILENT_PATHS, authStore, showToast });

    assert.equal(getCallCount(), 0);
    assert.equal(calls.length, 1, '403 is not silent/404 — should still toast');
});

test('handleApiError: 404 does NOT call handleUnauthorizedResponse and stays silent (no toast)', () => {
    const { authStore, getCallCount } = makeSpyAuthStore();
    const { showToast, calls } = makeToastSpy();

    const error: ApiErrorLike = { config: { url: '/watchlist/999' }, response: { status: 404, data: {} } };
    handleApiError(error, { silentPaths: SILENT_PATHS, authStore, showToast });

    assert.equal(getCallCount(), 0);
    assert.equal(calls.length, 0);
});

test('handleApiError: 401 on a silent path (e.g. /auth/me) still returns silently and does NOT double-invoke auth cleanup via toast path', () => {
    // /auth/me is in SILENT_PATHS (used by checkAuth); this asserts the
    // interceptor's silent-path short-circuit takes priority — checkAuth's
    // own catch block (classifyCheckAuthError) is what handles /auth/me's
    // 401, not this global interceptor, avoiding a double-invoke. This is
    // exactly the non-blocking Chris Medium note (SILENT_PATHS/auth-me
    // coupling) — asserted here as a real behavioral guarantee, not just a
    // comment.
    const { authStore, getCallCount } = makeSpyAuthStore();
    const { showToast, calls } = makeToastSpy();

    const error: ApiErrorLike = { config: { url: '/auth/me' }, response: { status: 401, data: {} } };
    handleApiError(error, { silentPaths: SILENT_PATHS, authStore, showToast });

    assert.equal(getCallCount(), 0, '/auth/me 401s are handled by checkAuth itself, not the global interceptor');
    assert.equal(calls.length, 0);
});

test('handleApiError: ECONNABORTED (timeout) shows the timeout toast and does not touch auth state', () => {
    const { authStore, getCallCount } = makeSpyAuthStore();
    const { showToast, calls } = makeToastSpy();

    const error: ApiErrorLike = { config: { url: '/portfolio' }, code: 'ECONNABORTED', message: 'timeout of 12000ms exceeded' };
    handleApiError(error, { silentPaths: SILENT_PATHS, authStore, showToast });

    assert.equal(getCallCount(), 0);
    assert.deepEqual(calls, [{ message: 'Request timed out — please try again', id: 'timeout' }]);
});

// ── Mutation-proof regression test — this is the direct repro of Chris's finding ──
test('mutation-proof: a dead 401 branch (equivalent to `if (false && status === 401)`) would fail this test', () => {
    const { authStore, getCallCount } = makeSpyAuthStore();
    const { showToast } = makeToastSpy();

    const error: ApiErrorLike = { config: { url: '/dashboard' }, response: { status: 401, data: {} } };
    handleApiError(error, { silentPaths: SILENT_PATHS, authStore, showToast });

    // If the 401 branch in handleApiError were ever mutated to a dead
    // branch (e.g. `if (false && status === 401)`), execution would fall
    // through to the final `deps.showToast(...)` line instead of calling
    // handleUnauthorizedResponse — this assertion on the REAL call count
    // (not source text) is what catches that.
    assert.equal(getCallCount(), 1);
});

// ── bd:shotockviz-tjh — decorative-background-read opt-out ──
//
// Rule chosen (recorded here + in apiErrorHandler.ts/api.ts): a request is
// marked `config.skipAuthClearOn401 = true` when the PAGE DOES NOT DEPEND ON
// IT — it already degrades to a cached/default value and swallows its own
// error. That flag, and ONLY that flag, exempts a 401 on it from clearing
// the global auth session. Everything else — any request with the flag
// unset, `false`, or simply never mentioning it — keeps today's behaviour
// (any 401 clears the session immediately, ADR-007). This is deliberately
// per-request opt-out, not a URL/path table like SILENT_PATHS: a URL table
// would silently swallow the OTHER status codes too (e.g. a real 422 on a
// PATCH the user just submitted), and would apply to every method on that
// path, not just the specific decorative GETs bd:shotockviz-tjh names.

test('handleApiError: 401 on a request flagged skipAuthClearOn401 does NOT clear the session and does not toast', () => {
    const { authStore, getCallCount } = makeSpyAuthStore();
    const { showToast, calls } = makeToastSpy();

    const error: ApiErrorLike = {
        config: { url: '/settings/trader', skipAuthClearOn401: true },
        response: { status: 401, data: {} },
    };
    handleApiError(error, { silentPaths: SILENT_PATHS, authStore, showToast });

    assert.equal(getCallCount(), 0, 'a decorative background read must not log the user out');
    assert.equal(calls.length, 0, 'a decorative background read must not surface a toast either — it already swallows its own error');
});

test('fail-safe: 401 on the SAME url with the flag unset (or false) still clears the session — opt-out is per-request, not per-path', () => {
    // Same URL as the test above ('/settings/trader') on purpose: proves the
    // exemption is driven by the explicit flag on that one request's config,
    // not by a path table that would blanket-exempt the whole endpoint
    // (e.g. the explicit PATCH /settings/trader Save action, which MUST
    // still log a genuinely-expired trader out).
    const unmarked = makeSpyAuthStore();
    const errorUnmarked: ApiErrorLike = {
        config: { url: '/settings/trader' },
        response: { status: 401, data: {} },
    };
    handleApiError(errorUnmarked, { silentPaths: SILENT_PATHS, authStore: unmarked.authStore, showToast: makeToastSpy().showToast });
    assert.equal(unmarked.getCallCount(), 1, 'no flag present -> fail safe -> today\'s behaviour (clears session)');

    const explicitFalse = makeSpyAuthStore();
    const errorFalse: ApiErrorLike = {
        config: { url: '/settings/trader', skipAuthClearOn401: false },
        response: { status: 401, data: {} },
    };
    handleApiError(errorFalse, { silentPaths: SILENT_PATHS, authStore: explicitFalse.authStore, showToast: makeToastSpy().showToast });
    assert.equal(explicitFalse.getCallCount(), 1, 'flag explicitly false -> still clears session');
});

test('flagged request still toasts on a NON-401 failure (e.g. 500) — the opt-out only narrows the 401/auth-clear branch', () => {
    const { authStore, getCallCount } = makeSpyAuthStore();
    const { showToast, calls } = makeToastSpy();

    const error: ApiErrorLike = {
        config: { url: '/settings/trader', skipAuthClearOn401: true },
        response: { status: 500, data: { detail: 'boom' } },
    };
    handleApiError(error, { silentPaths: SILENT_PATHS, authStore, showToast });

    assert.equal(getCallCount(), 0);
    assert.equal(calls.length, 1, 'the flag must not become a blanket silent-path for every status code');
});

test('mutation-proof: removing/inverting the skipAuthClearOn401 check (dead branch) would fail the flagged-401 test above', () => {
    // Equivalent to Chris's `status === 401` -> `false && status === 401`
    // technique (apiErrorHandler.ts header), applied to the NEW branch: if
    // `error.config?.skipAuthClearOn401` were mutated to
    // `false && error.config?.skipAuthClearOn401`, this call would fall
    // through to handleUnauthorizedResponse() and callCount would be 1, not
    // 0 — this assertion is on the real call count, not source text.
    const { authStore, getCallCount } = makeSpyAuthStore();
    const { showToast } = makeToastSpy();

    const error: ApiErrorLike = {
        config: { url: '/settings/trader', skipAuthClearOn401: true },
        response: { status: 401, data: {} },
    };
    handleApiError(error, { silentPaths: SILENT_PATHS, authStore, showToast });

    assert.equal(getCallCount(), 0);
});

test('isSilentPath: matches configured substrings', () => {
    assert.equal(isSilentPath('/quote/PTT.BK', SILENT_PATHS), true);
    assert.equal(isSilentPath('/portfolio', SILENT_PATHS), false);
});

test('extractErrorMessage: prefers envelope meta.error.message, falls back to detail, then error.message', () => {
    assert.equal(
        extractErrorMessage({ response: { data: { meta: { error: { message: 'env msg' } }, detail: 'ignored' } } }),
        'env msg',
    );
    assert.equal(
        extractErrorMessage({ response: { data: { detail: 'plain detail' } } }),
        'plain detail',
    );
    assert.equal(
        extractErrorMessage({ response: { data: { detail: [{ msg: 'a' }, { msg: 'b' }] } } }),
        'a, b',
    );
    assert.equal(
        extractErrorMessage({ message: 'network down' }),
        'network down',
    );
});
