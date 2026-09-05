import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildTransactionUpdatePatch } from './transactionEditDiff.ts';

const ORIGINAL = {
    qty: 10,
    price: 150,
    fee: 1,
    currency: 'USD',
    date: '2026-01-10',
    note: 'initial',
};

const unchangedForm = () => ({
    qty: '10',
    price: '150',
    fee: '1',
    currency: 'USD',
    date: '2026-01-10',
    note: 'initial',
});

test('no changes: empty patch', () => {
    assert.deepEqual(buildTransactionUpdatePatch(ORIGINAL, unchangedForm()), {});
});

test('qty changed only: patch has just qty', () => {
    const form = { ...unchangedForm(), qty: '20' };
    assert.deepEqual(buildTransactionUpdatePatch(ORIGINAL, form), { qty: 20 });
});

test('price changed only', () => {
    const form = { ...unchangedForm(), price: '160' };
    assert.deepEqual(buildTransactionUpdatePatch(ORIGINAL, form), { price: 160 });
});

test('fee changed, blank fee treated as 0', () => {
    const form = { ...unchangedForm(), fee: '' };
    assert.deepEqual(buildTransactionUpdatePatch(ORIGINAL, form), { fee: 0 });
});

test('currency changed: case-insensitive compare, patch carries uppercased value', () => {
    const form = { ...unchangedForm(), currency: 'thb' };
    assert.deepEqual(buildTransactionUpdatePatch(ORIGINAL, form), { currency: 'THB' });
});

test('currency unchanged when original had no currency and form defaults to THB', () => {
    const original = { ...ORIGINAL, currency: null };
    const form = { ...unchangedForm(), currency: 'THB' };
    assert.deepEqual(buildTransactionUpdatePatch(original, form), {});
});

test('date changed: included (disabled in the UI today, but the diff itself is honest)', () => {
    const form = { ...unchangedForm(), date: '2026-02-01' };
    assert.deepEqual(buildTransactionUpdatePatch(ORIGINAL, form), { date: '2026-02-01' });
});

test('note changed, including clearing it to empty', () => {
    const form = { ...unchangedForm(), note: '' };
    assert.deepEqual(buildTransactionUpdatePatch(ORIGINAL, form), { note: '' });
});

test('note unchanged when original is null and form is empty string', () => {
    const original = { ...ORIGINAL, note: null };
    const form = { ...unchangedForm(), note: '' };
    assert.deepEqual(buildTransactionUpdatePatch(original, form), {});
});

test('fx_rate is never a key in the patch shape (TransactionFormValues has no such field)', () => {
    const form = { ...unchangedForm(), qty: '99' };
    const patch = buildTransactionUpdatePatch(ORIGINAL, form);
    assert.equal('fx_rate' in patch, false);
});

test('multiple fields changed at once', () => {
    const form = { ...unchangedForm(), qty: '5', note: 'trimmed position' };
    assert.deepEqual(buildTransactionUpdatePatch(ORIGINAL, form), { qty: 5, note: 'trimmed position' });
});
