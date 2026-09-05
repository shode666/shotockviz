import { test } from 'node:test';
import assert from 'node:assert/strict';
import { getCurrentSection } from './scrollspy.ts';

test('getCurrentSection: at top of page returns first section', () => {
    assert.equal(getCurrentSection([0, 400], 0), 0);
});

test('getCurrentSection: scrolled past first section top returns second', () => {
    assert.equal(getCurrentSection([0, 400], 401), 1);
});

test('getCurrentSection: exactly at a section top counts as that section', () => {
    assert.equal(getCurrentSection([0, 400], 400), 1);
});

test('getCurrentSection: scrolled just before second section stays on first', () => {
    assert.equal(getCurrentSection([0, 400], 399), 0);
});

test('getCurrentSection: empty section list returns 0', () => {
    assert.equal(getCurrentSection([], 250), 0);
});

test('getCurrentSection: three sections picks last one passed', () => {
    assert.equal(getCurrentSection([0, 200, 600], 650), 2);
});

// bd:ui-honesty-2026-09 Chris Medium #4 — a missing section's top must never
// win as "current". Callers now map a missing DOM element to Infinity
// (SettingsPage.tsx) instead of 0, so it can never satisfy `scrollY >= top`.
test('getCurrentSection: a missing section (top=Infinity) never wins as current', () => {
    assert.equal(getCurrentSection([0, Infinity], 500), 0);
});
