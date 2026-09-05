import { test } from 'node:test'
import assert from 'node:assert/strict'
import { isOverflowPath, getOverflowItems, OVERFLOW_PATHS } from './mobileNav.ts'

test('isOverflowPath: true for every overflow route', () => {
    for (const p of OVERFLOW_PATHS) {
        assert.equal(isOverflowPath(p), true, p)
    }
})

test('isOverflowPath: false for core tab routes and unknowns', () => {
    for (const p of ['/', '/dashboard', '/screener', '/portfolio', '/alerts', '/nope']) {
        assert.equal(isOverflowPath(p), false, p)
    }
})

test('getOverflowItems: guest sees News, Settings, Login in that order', () => {
    assert.deepEqual(
        getOverflowItems(false).map((i) => i.to),
        ['/news', '/settings', '/login'],
    )
})

test('getOverflowItems: authenticated user sees no Login entry', () => {
    const items = getOverflowItems(true)
    assert.deepEqual(items.map((i) => i.to), ['/news', '/settings'])
    assert.equal(items.some((i) => i.to === '/login'), false)
})
