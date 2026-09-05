// bd:shotockviz-282 — mobile "More" sheet IA (Uma).
// The 5 core trading tabs stay untouched; secondary destinations live behind
// a single "More" disclosure. Pure logic here so it runs under node --test.
//
// bd:shotockviz-g7k — Logout lives in the Navbar user dropdown, which is
// `hidden md:flex`, so a logged-in mobile user had no way to sign out.
// Uma's 282 notes deliberately left this out of that bead's scope rather
// than smuggle it in; her instruction there: mirror how Login is shown only
// to guests — Logout shows only when authenticated, same slot in the sheet.
// Logout is not a route (no page to Link to), so items are now a
// discriminated union: a navigable 'link' entry vs a 'logout' action entry
// the component wires to authStore's logout().

export interface OverflowLinkItem {
    kind: 'link'
    to: '/news' | '/settings' | '/login'
    label: string
}

export interface OverflowLogoutItem {
    kind: 'logout'
    label: string
}

export type OverflowItem = OverflowLinkItem | OverflowLogoutItem

/** Routes that live behind the mobile "More" sheet (no dedicated tab). */
export const OVERFLOW_PATHS = ['/news', '/settings', '/login'] as const

/** True when the current route is one the "More" tab represents —
 *  used to light the More tab up, since those routes have no tab of their own. */
export function isOverflowPath(path: string): boolean {
    return (OVERFLOW_PATHS as readonly string[]).includes(path)
}

/** Sheet entries. Login appears only for guests — a logged-in user has no
 *  reason to visit /login, and showing it would be a dishonest affordance.
 *  Logout mirrors that exactly in the other direction: only an authenticated
 *  user has anything to log out of. */
export function getOverflowItems(isAuthenticated: boolean): OverflowItem[] {
    const items: OverflowItem[] = [
        { kind: 'link', to: '/news', label: 'News' },
        { kind: 'link', to: '/settings', label: 'Settings' },
    ]
    if (isAuthenticated) {
        items.push({ kind: 'logout', label: 'Logout' })
    } else {
        items.push({ kind: 'link', to: '/login', label: 'Login' })
    }
    return items
}
