/**
 * useHydrated — true once React has hydrated this component on the client.
 *
 * bd:shotockviz-6h3 — the SSR markup is on screen before the JS bundle
 * attaches handlers; during that window clicks/keys were silently dropped.
 * Controls that only work via JS render their honest "not ready yet" state
 * (`inert` / `disabled` + .awaiting-hydration) while this is false.
 *
 * useSyncExternalStore with a distinct server snapshot is the canonical
 * pattern: the server (and the hydration render, which must match it)
 * sees `false`, so `inert`/`disabled` are baked into the SSR HTML itself
 * and the browser blocks interaction natively before any JS exists.
 * React then re-renders with the client snapshot (`true`) immediately at
 * hydration — no extra effect tick, and components mounted later (SPA
 * navigation) start at `true`, so there is no disabled flash after boot.
 */
import { useSyncExternalStore } from 'react';

const emptySubscribe = () => () => {};

export default function useHydrated(): boolean {
    return useSyncExternalStore(
        emptySubscribe,
        () => true,   // client snapshot — after hydration
        () => false,  // server snapshot — SSR + hydration render
    );
}
