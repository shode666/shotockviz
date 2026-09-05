// bd:shotockviz-282 — mobile "More" sheet IA (Uma).
// The 5 core trading tabs stay untouched; secondary destinations live behind
// a single "More" disclosure. Pure logic here so it runs under node --test.

export interface OverflowItem {
    to: '/news' | '/settings' | '/login'
    label: string
}

/** Routes that live behind the mobile "More" sheet (no dedicated tab). */
export const OVERFLOW_PATHS = ['/news', '/settings', '/login'] as const

/** True when the current route is one the "More" tab represents —
 *  used to light the More tab up, since those routes have no tab of their own. */
export function isOverflowPath(path: string): boolean {
    return (OVERFLOW_PATHS as readonly string[]).includes(path)
}

/** Sheet entries. Login appears only for guests — a logged-in user has no
 *  reason to visit /login, and showing it would be a dishonest affordance. */
export function getOverflowItems(isAuthenticated: boolean): OverflowItem[] {
    const items: OverflowItem[] = [
        { to: '/news', label: 'News' },
        { to: '/settings', label: 'Settings' },
    ]
    if (!isAuthenticated) items.push({ to: '/login', label: 'Login' })
    return items
}
