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

test('getOverflowItems: guest sees News, Settings, Login (link) in that order — no Logout', () => {
    const items = getOverflowItems(false)
    assert.deepEqual(items.map((i) => i.kind), ['link', 'link', 'link'])
    assert.deepEqual(
        items.map((i) => (i.kind === 'link' ? i.to : null)),
        ['/news', '/settings', '/login'],
    )
    assert.equal(items.some((i) => i.kind === 'logout'), false)
})

// bd:shotockviz-g7k — mirror of the guest-Login check above: an
// authenticated mobile user sees Logout in Login's slot, and never Login.
test('getOverflowItems: authenticated user sees Logout instead of Login', () => {
    const items = getOverflowItems(true)
    assert.deepEqual(items.map((i) => i.kind), ['link', 'link', 'logout'])
    assert.equal(items.some((i) => i.kind === 'link' && i.to === '/login'), false)
    assert.equal(items[2].label, 'Logout')
})
