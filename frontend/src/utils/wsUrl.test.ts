import { test } from 'node:test';
import assert from 'node:assert/strict';
import { buildWsUrl } from './wsUrl.ts';

// bd:shotockviz-pls — authenticated WS handshake URL.

test('buildWsUrl: https page → wss with token query param', () => {
    assert.equal(
        buildWsUrl('https:', 'stock.shode.dev', 'abc.def.ghi'),
        'wss://stock.shode.dev/api/ws/prices?token=abc.def.ghi',
    );
});

test('buildWsUrl: http page → ws (local dev without TLS)', () => {
    assert.equal(
        buildWsUrl('http:', 'localhost:3000', 't'),
        'ws://localhost:3000/api/ws/prices?token=t',
    );
});

test('buildWsUrl: token is URL-encoded so a weird token cannot break the URL', () => {
    assert.equal(
        buildWsUrl('https:', 'localhost', 'a+b/c=&d'),
        'wss://localhost/api/ws/prices?token=a%2Bb%2Fc%3D%26d',
    );
});
