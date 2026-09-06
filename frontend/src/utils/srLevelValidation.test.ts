import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateSrLevelPrice } from './srLevelValidation.ts';

test('empty price -> required-field message', () => {
    assert.equal(validateSrLevelPrice(''), 'กรุณาระบุราคา');
});

test('whitespace-only price -> required-field message', () => {
    assert.equal(validateSrLevelPrice('   '), 'กรุณาระบุราคา');
});

test('zero price -> rejected (backend requires price > 0)', () => {
    assert.equal(validateSrLevelPrice('0'), 'ราคาต้องเป็นตัวเลขมากกว่า 0');
});

test('negative price -> rejected', () => {
    assert.equal(validateSrLevelPrice('-5'), 'ราคาต้องเป็นตัวเลขมากกว่า 0');
});

test('non-numeric price -> rejected', () => {
    assert.equal(validateSrLevelPrice('abc'), 'ราคาต้องเป็นตัวเลขมากกว่า 0');
});

test('valid positive integer price -> no error', () => {
    assert.equal(validateSrLevelPrice('150'), null);
});

test('valid positive decimal price -> no error', () => {
    assert.equal(validateSrLevelPrice('150.75'), null);
});
