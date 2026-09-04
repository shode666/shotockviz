/**
 * Pure WebSocket `data_ready` message helpers.
 *
 * Split out from useWebSocket.ts (which pulls in `@/store/*` path-alias
 * imports that only Vite's bundler resolves) so this logic is importable
 * by the plain Node test runner with zero build step — bd:ux-2026-09
 * carried-in bug fix + regression test.
 */
export interface WsDataReadyLike {
    type?: string;
    data_type?: string;
    symbol?: string;
    timeframe?: string;
}

/**
 * True when a `data_ready` WS message carries a fresh quote — the signal that
 * `usePriceUpdates` (sidebar/watchlist) should refetch immediately instead of
 * waiting for its next 60s poll.
 */
export function shouldBumpDataVersion(data: WsDataReadyLike | null | undefined): boolean {
    return !!data && data.type === 'data_ready' && data.data_type === 'quote';
}
