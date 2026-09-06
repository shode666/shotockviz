import { test } from 'node:test';
import assert from 'node:assert/strict';
import {
    PRE_HYDRATION_CAPTURE_SCRIPT,
    consumePreHydrationIntents,
    type PreHydrationWindow,
    type PreHydrationBridge,
} from './prehydration.ts';

/** Minimal window stand-in the inline script can run against. */
function makeFakeWindow() {
    const listeners: Record<string, ((e: unknown) => void)[]> = {};
    const w = {
        addEventListener(type: string, fn: (e: unknown) => void) {
            (listeners[type] ??= []).push(fn);
        },
        removeEventListener(type: string, fn: (e: unknown) => void) {
            listeners[type] = (listeners[type] ?? []).filter(f => f !== fn);
        },
        dispatch(type: string, e: unknown) {
            for (const fn of listeners[type] ?? []) fn(e);
        },
        listenerCount(type: string) {
            return (listeners[type] ?? []).length;
        },
    } as PreHydrationWindow & {
        dispatch: (type: string, e: unknown) => void;
        listenerCount: (type: string) => number;
    };
    return w;
}

function key(overrides: Partial<{ metaKey: boolean; ctrlKey: boolean; key: string }>) {
    let prevented = false;
    return {
        metaKey: false, ctrlKey: false, key: '',
        preventDefault() { prevented = true; },
        get defaultPrevented() { return prevented; },
        ...overrides,
    };
}

function bootScript(w: ReturnType<typeof makeFakeWindow>) {
    // Run the real inline script against the fake window — this is exactly
    // what the browser executes from <head> before the bundle loads.
    new Function('window', PRE_HYDRATION_CAPTURE_SCRIPT)(w);
}

test('inline script is syntactically valid and installs the bridge + keydown listener', () => {
    const w = makeFakeWindow();
    bootScript(w);
    assert.ok(w.__shotockPreHydration, 'bridge global installed');
    assert.deepEqual(w.__shotockPreHydration!.intents, []);
    assert.equal(w.listenerCount('keydown'), 1);
});

test('Cmd+K and Ctrl+K are queued and preventDefault-ed; other keys are not', () => {
    const w = makeFakeWindow();
    bootScript(w);

    const cmdK = key({ metaKey: true, key: 'k' });
    w.dispatch('keydown', cmdK);
    assert.equal(cmdK.defaultPrevented, true, 'Cmd+K default prevented');

    const ctrlK = key({ ctrlKey: true, key: 'k' });
    w.dispatch('keydown', ctrlK);

    const plainK = key({ key: 'k' });                    // no modifier — typing
    const cmdJ = key({ metaKey: true, key: 'j' });       // other shortcut
    const esc = key({ key: 'Escape' });
    w.dispatch('keydown', plainK);
    w.dispatch('keydown', cmdJ);
    w.dispatch('keydown', esc);
    assert.equal(plainK.defaultPrevented, false);
    assert.equal(cmdJ.defaultPrevented, false);

    assert.deepEqual(w.__shotockPreHydration!.intents, ['search', 'search']);
});

test('consume returns openSearch=true, tears down the listener and the global', () => {
    const w = makeFakeWindow();
    bootScript(w);
    w.dispatch('keydown', key({ metaKey: true, key: 'k' }));

    const result = consumePreHydrationIntents(w);
    assert.deepEqual(result, { openSearch: true });
    assert.equal(w.listenerCount('keydown'), 0, 'bootstrap listener removed');
    assert.equal(w.__shotockPreHydration, undefined, 'global removed');
});

test('consume with nothing queued → openSearch=false, still tears down', () => {
    const w = makeFakeWindow();
    bootScript(w);
    assert.deepEqual(consumePreHydrationIntents(w), { openSearch: false });
    assert.equal(w.listenerCount('keydown'), 0);
});

test('consume is safe when the inline script never ran (no bridge)', () => {
    assert.deepEqual(consumePreHydrationIntents({}), { openSearch: false });
});

test('consume is idempotent — second call is a no-op false', () => {
    const w = makeFakeWindow();
    bootScript(w);
    w.dispatch('keydown', key({ ctrlKey: true, key: 'k' }));
    assert.equal(consumePreHydrationIntents(w).openSearch, true);
    assert.equal(consumePreHydrationIntents(w).openSearch, false);
});

test('a throwing/foreign teardown never breaks consume', () => {
    const w: PreHydrationWindow = {
        __shotockPreHydration: {
            intents: ['search'],
            teardown() { throw new Error('boom'); },
        } satisfies PreHydrationBridge,
    };
    assert.deepEqual(consumePreHydrationIntents(w), { openSearch: true });
    assert.equal(w.__shotockPreHydration, undefined);
});
