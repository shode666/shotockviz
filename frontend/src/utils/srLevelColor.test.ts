/**
 * Unit tests — resolveSrLevelColor / resolveSrLevelTitle (bd:features-2026-09
 * slice 2). Run: `cd frontend && npm test` (== `node --test`), same runner
 * convention as src/hooks/useWebSocket.test.ts.
 */
import { test } from 'node:test';
import assert from 'node:assert/strict';
import { resolveSrLevelColor, resolveSrLevelTitle, SR_LEVEL_FALLBACK_COLOR } from './srLevelColor.ts';

test('resolveSrLevelColor uses the row color when present', () => {
    assert.equal(
        resolveSrLevelColor({ color: '#fde047', level_type: 'support' }),
        '#fde047',
    );
    assert.equal(
        resolveSrLevelColor({ color: '#a78bfa', level_type: 'resistance' }),
        '#a78bfa',
    );
});

test('resolveSrLevelColor falls back to yellow for support when color is null', () => {
    assert.equal(
        resolveSrLevelColor({ color: null, level_type: 'support' }),
        SR_LEVEL_FALLBACK_COLOR.support,
    );
});

test('resolveSrLevelColor falls back to magenta for resistance when color is null', () => {
    assert.equal(
        resolveSrLevelColor({ color: null, level_type: 'resistance' }),
        SR_LEVEL_FALLBACK_COLOR.resistance,
    );
});

test('resolveSrLevelColor treats missing color field same as null', () => {
    assert.equal(
        resolveSrLevelColor({ level_type: 'support' }),
        SR_LEVEL_FALLBACK_COLOR.support,
    );
});

test('resolveSrLevelColor treats empty-string color as absent (falls back)', () => {
    assert.equal(
        resolveSrLevelColor({ color: '', level_type: 'resistance' }),
        SR_LEVEL_FALLBACK_COLOR.resistance,
    );
});

test('resolveSrLevelColor returns a neutral default for an unrecognized level_type with no color', () => {
    assert.equal(
        resolveSrLevelColor({ color: null, level_type: 'bogus' }),
        '#9ca3af',
    );
});

test('resolveSrLevelTitle returns the tag when present', () => {
    assert.equal(resolveSrLevelTitle({ tag: 'S1' }), 'S1');
    assert.equal(resolveSrLevelTitle({ tag: 'R2' }), 'R2');
});

test('resolveSrLevelTitle returns empty string when tag is null or missing', () => {
    assert.equal(resolveSrLevelTitle({ tag: null }), '');
    assert.equal(resolveSrLevelTitle({}), '');
});
