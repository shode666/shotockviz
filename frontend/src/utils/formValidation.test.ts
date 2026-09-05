import { test } from 'node:test';
import assert from 'node:assert/strict';
import { validateAlertForm, validateTransactionForm } from './formValidation.ts';

test('validateAlertForm: empty symbol and value both flagged', () => {
    const errors = validateAlertForm({ symbol: '', value: '' });
    assert.equal(errors.symbol, 'กรุณาระบุ symbol');
    assert.equal(errors.value, 'กรุณาระบุค่า');
});

test('validateAlertForm: whitespace-only symbol flagged', () => {
    const errors = validateAlertForm({ symbol: '   ', value: '10' });
    assert.equal(errors.symbol, 'กรุณาระบุ symbol');
    assert.equal(errors.value, undefined);
});

test('validateAlertForm: valid form returns no errors', () => {
    const errors = validateAlertForm({ symbol: 'PTT', value: '40' });
    assert.deepEqual(errors, {});
});

test('validateTransactionForm: all empty fields flagged', () => {
    const errors = validateTransactionForm({ symbol: '', qty: '', price: '' });
    assert.equal(errors.symbol, 'กรุณาระบุ symbol');
    assert.equal(errors.qty, 'กรุณาระบุจำนวน');
    assert.equal(errors.price, 'กรุณาระบุราคา');
});

test('validateTransactionForm: partial (only qty missing)', () => {
    const errors = validateTransactionForm({ symbol: 'AAPL', qty: '', price: '150' });
    assert.deepEqual(Object.keys(errors), ['qty']);
});

test('validateTransactionForm: valid form returns no errors', () => {
    const errors = validateTransactionForm({ symbol: 'AAPL', qty: '10', price: '150' });
    assert.deepEqual(errors, {});
});
