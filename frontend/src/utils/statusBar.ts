/**
 * Pure formatting for StatusBar's "last update" text.
 *
 * `timestamp` is the `_key` from appStore.dataReadyPayload — the moment the
 * most recent `data_ready` WS message reached this client (not a wall clock).
 * `null` means no `data_ready` has arrived yet this session — show "—"
 * rather than fabricating a time (ADR-UH-001 / Bella F3 AC, Q2-A).
 */
export function formatLastUpdate(timestamp: number | null, now: number): string {
    if (timestamp === null) return '—';
    return new Date(timestamp).toLocaleTimeString('en-GB', { hour12: false });
}

/**
 * Shape of appStore.dataReadyPayload as consumed by StatusBar — see
 * bd:ui-honesty-2026-09 F3 r2 (`03b-bella-spec-r2-F3.md`).
 */
export interface DataReadyPayloadLike {
    data_type?: string;
    symbol?: string;
    _key?: number;
}

/**
 * Returns the `_key` timestamp only when `payload` is a quote-type data_ready
 * for the symbol currently on screen (or a broadcast `symbol: "*"`).
 * Returns null otherwise — including for history/fundamentals/dashboard
 * payloads regardless of symbol (bd:ui-honesty-2026-09 F3 r2 — Chris finding).
 */
export function getLastQuoteTimestamp(
    payload: DataReadyPayloadLike | null | undefined,
    selectedSymbol: string
): number | null {
    if (!payload) return null;
    if (payload.data_type !== 'quote') return null;
    if (payload.symbol !== selectedSymbol && payload.symbol !== '*') return null;
    return payload._key ?? null;
}

/**
 * Component-local "remembered" last-quote-timestamp state, keyed to the
 * symbol it belongs to. Lives outside the store (Bella F3 r2 hard
 * constraint: no new store field, `setDataReadyPayload`/`useWebSocket.ts`
 * untouched) because `appStore.dataReadyPayload` is a single slot the store
 * overwrites on EVERY `data_ready` message (`useWebSocket.ts:77`) — deriving
 * the timestamp fresh from that slot on every render means a later
 * non-qualifying message (e.g. a `history`/`fundamentals` sweep for the same
 * or another symbol) wipes an already-earned timestamp back to `null`, which
 * violates AC3/AC4 ("must not change from its prior value"). This is why
 * `StatusBar.tsx` remembers it in local state instead of calling
 * `getLastQuoteTimestamp` directly for display.
 */
export interface LastUpdateState {
    symbol: string;
    timestamp: number | null;
}

/**
 * Pure reducer: given the previously remembered `{ symbol, timestamp }` and
 * the latest raw `dataReadyPayload` from the store, returns the next
 * remembered state.
 *
 * - Selected symbol changed since `prev` → old value is dropped (AC5); the
 *   new payload is still checked against the NEW symbol in the same step
 *   (so a payload that already qualifies for the new symbol — e.g. a
 *   `symbol: "*"` broadcast — is not needlessly delayed a frame).
 * - Same symbol, payload qualifies (`getLastQuoteTimestamp` non-null) →
 *   timestamp advances (AC1/AC2).
 * - Same symbol, payload does not qualify (wrong `data_type` and/or wrong
 *   symbol) → `prev` is returned UNCHANGED, by reference, so callers can
 *   cheaply detect "nothing to do" (AC3/AC4 — this is the exact regression
 *   Quinn's F3 r3 review pinned: a non-qualifying message must never reset
 *   an already-earned timestamp).
 */
export function nextLastUpdate(
    prev: LastUpdateState,
    payload: DataReadyPayloadLike | null | undefined,
    selectedSymbol: string
): LastUpdateState {
    const qualifying = getLastQuoteTimestamp(payload, selectedSymbol);

    if (prev.symbol !== selectedSymbol) {
        return { symbol: selectedSymbol, timestamp: qualifying };
    }

    if (qualifying !== null) {
        return { symbol: selectedSymbol, timestamp: qualifying };
    }

    return prev;
}
