import useAuthStore from '@/store/authStore';

// bd:deps-2026-09 S3 — `login`/`register` were destructured here but never
// existed on the store post-S1 (ADR-007 removed password auth; only
// googleLogin/logout/checkAuth remain, authStore.ts). Silently resolved to
// `undefined` in plain JS; TS now catches it. This hook has zero import
// sites repo-wide (dead code) — corrected to the real store shape rather
// than typed around the drift.
export default function useAuth() {
    const { user, isAuthenticated, isLoading, googleLogin, logout, checkAuth } =
        useAuthStore();
    return { user, isAuthenticated, isLoading, googleLogin, logout, checkAuth };
}
