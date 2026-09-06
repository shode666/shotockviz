/**
 * Pre-hydration keyboard intent queue — bd:shotockviz-6h3.
 *
 * Pointer controls get an honest `inert`/`disabled` state until hydration
 * (see useHydrated.ts), but a keyboard shortcut has no pixels to make
 * inert: the ⌘K hint in the Navbar advertises it the moment the SSR HTML
 * paints. So an inline <script> in <head> (PRE_HYDRATION_CAPTURE_SCRIPT,
 * injected via the root route's head() → scripts) runs before the app
 * bundle, captures Cmd/Ctrl+K, and queues the *intent* ("open search").
 * After hydration, SearchModal consumes the queue and opens.
 *
 * Only this one idempotent intent is queued — arbitrary clicks are NOT
 * recorded/replayed, deliberately: replaying a pointer event against a
 * re-rendered DOM is ambiguous (wrong target, double toggle), and an
 * action that "lands" seconds after the click is worse than one that
 * visibly cannot be attempted.
 */

export const SEARCH_INTENT = 'search';

/** Window global the inline script and the app agree on. */
export interface PreHydrationBridge {
    intents: string[];
    /** Removes the bootstrap listener + deletes the global. */
    teardown: () => void;
}

export interface PreHydrationWindow {
    __shotockPreHydration?: PreHydrationBridge;
}

/**
 * Inline script injected into <head> by __root.tsx. Must stay
 * self-contained ES5 — it runs before any bundle exists.
 * Key matching (`e.key === 'k'` + meta/ctrl) mirrors the live listener
 * in SearchModal.tsx so pre- and post-hydration behave identically.
 */
export const PRE_HYDRATION_CAPTURE_SCRIPT = [
    '(function () {',
    '  var intents = [];',
    '  function onKey(e) {',
    "    if ((e.metaKey || e.ctrlKey) && e.key === 'k') {",
    '      e.preventDefault();',
    "      intents.push('search');",
    '    }',
    '  }',
    "  window.addEventListener('keydown', onKey);",
    '  window.__shotockPreHydration = {',
    '    intents: intents,',
    '    teardown: function () {',
    "      window.removeEventListener('keydown', onKey);",
    '      try { delete window.__shotockPreHydration; } catch (err) {}',
    '    }',
    '  };',
    '})();',
].join('\n');

/**
 * Consume whatever was queued before hydration and tear the bridge down.
 * Idempotent: second call (or no inline script at all) → all-false.
 */
export function consumePreHydrationIntents(w: PreHydrationWindow): { openSearch: boolean } {
    const bridge = w.__shotockPreHydration;
    if (!bridge || !Array.isArray(bridge.intents)) return { openSearch: false };
    const openSearch = bridge.intents.includes(SEARCH_INTENT);
    try { bridge.teardown(); } catch { /* bridge must never break the app */ }
    delete w.__shotockPreHydration; // in case teardown was a foreign no-op
    return { openSearch };
}
