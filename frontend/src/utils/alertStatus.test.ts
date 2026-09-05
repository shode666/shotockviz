import { test } from 'node:test';
import assert from 'node:assert/strict';
import { getAlertStatusKey } from './alertStatus.ts';

test('getAlertStatusKey: TRIGGERED status', () => {
    assert.equal(getAlertStatusKey({ status: 'TRIGGERED', is_active: true }), 'triggered');
});

test('getAlertStatusKey: active when is_active true and no special status', () => {
    assert.equal(getAlertStatusKey({ status: null, is_active: true }), 'active');
});

test('getAlertStatusKey: inactive when is_active false and no special status', () => {
    assert.equal(getAlertStatusKey({ status: null, is_active: false }), 'inactive');
});

test('getAlertStatusKey: missing status field defaults through is_active', () => {
    assert.equal(getAlertStatusKey({ is_active: true }), 'active');
    assert.equal(getAlertStatusKey({ is_active: false }), 'inactive');
});
