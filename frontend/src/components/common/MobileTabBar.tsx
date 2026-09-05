import { useEffect, useRef, useState } from 'react'
import { Link, useMatches } from '@tanstack/react-router'
import {
    LayoutDashboard, TrendingUp, SlidersHorizontal, Briefcase, Bell,
    MoreHorizontal, Newspaper, Settings, LogIn,
} from 'lucide-react'
import useAuthStore from '@/store/authStore'
import { isOverflowPath, getOverflowItems, type OverflowItem } from '@/utils/mobileNav'

// 5 core tabs per bd:ux-2026-09 — the primary trading workflow stays within
// thumb reach and untouched in order. bd:shotockviz-282 (Uma IA decision):
// secondary destinations (/news, /settings, /login) are reachable through a
// 6th "More" tab that opens a bottom sheet — HIG "More" pattern — instead of
// promoting them to top-level tabs.
const tabItems = [
    { to: '/dashboard', label: 'Dashboard', Icon: LayoutDashboard },
    { to: '/', label: 'Chart', Icon: TrendingUp },
    { to: '/screener', label: 'Screener', Icon: SlidersHorizontal },
    { to: '/portfolio', label: 'Portfolio', Icon: Briefcase },
    { to: '/alerts', label: 'Alerts', Icon: Bell },
]

const SHEET_ICONS: Record<OverflowItem['to'], typeof Newspaper> = {
    '/news': Newspaper,
    '/settings': Settings,
    '/login': LogIn,
}

export default function MobileTabBar() {
    const matches = useMatches()
    const currentPath = matches[matches.length - 1]?.pathname || '/'
    const { isAuthenticated } = useAuthStore()

    const [isMoreOpen, setIsMoreOpen] = useState(false)
    const moreButtonRef = useRef<HTMLButtonElement>(null)
    const firstItemRef = useRef<HTMLAnchorElement>(null)

    // Keyboard dismiss: Escape closes the sheet and returns focus to the
    // trigger. Focus is NOT trapped — Tab moves on naturally (disclosure
    // pattern, not a modal dialog).
    useEffect(() => {
        if (!isMoreOpen) return
        const onKeyDown = (e: KeyboardEvent) => {
            if (e.key === 'Escape') {
                setIsMoreOpen(false)
                moreButtonRef.current?.focus()
            }
        }
        document.addEventListener('keydown', onKeyDown)
        return () => document.removeEventListener('keydown', onKeyDown)
    }, [isMoreOpen])

    // Move focus into the sheet when it opens
    useEffect(() => {
        if (isMoreOpen) firstItemRef.current?.focus()
    }, [isMoreOpen])

    // Route changed (item chosen or back/deep link) → sheet closes
    useEffect(() => {
        setIsMoreOpen(false)
    }, [currentPath])

    const moreActive = isMoreOpen || isOverflowPath(currentPath)
    const overflowItems = getOverflowItems(isAuthenticated)

    return (
        <>
            {isMoreOpen && (
                <>
                    {/* Backdrop — pointer dismiss */}
                    <div
                        className="md:hidden fixed inset-0 z-40"
                        aria-hidden="true"
                        onClick={() => setIsMoreOpen(false)}
                        style={{ background: 'rgba(0, 0, 0, 0.3)' }}
                    />
                    <nav
                        id="mobile-more-sheet"
                        aria-label="เมนูเพิ่มเติม"
                        className="glass-dropdown md:hidden fixed z-50"
                        style={{ left: 8, right: 8, bottom: 64 }}
                    >
                        {overflowItems.map(({ to, label }, i) => {
                            const Icon = SHEET_ICONS[to]
                            const isActive = currentPath === to
                            return (
                                <Link
                                    key={to}
                                    to={to}
                                    ref={i === 0 ? firstItemRef : undefined}
                                    aria-current={isActive ? 'page' : undefined}
                                    className="flex items-center gap-3 px-4 text-[13px] font-semibold transition-colors"
                                    style={{
                                        minHeight: 48,
                                        color: isActive ? 'var(--color-accent-text)' : 'var(--color-text)',
                                        background: isActive ? 'var(--surface-3)' : 'transparent',
                                    }}
                                >
                                    <Icon size={16} aria-hidden="true" />
                                    {label}
                                </Link>
                            )
                        })}
                    </nav>
                </>
            )}

            <nav
                aria-label="เมนูล่าง"
                className="md:hidden flex fixed left-0 right-0 bottom-0 z-40"
                style={{
                    height: 56,
                    borderTop: '1px solid var(--color-border)',
                    background: 'var(--surface-1)',
                    backdropFilter: 'var(--glass-blur-nav)',
                    WebkitBackdropFilter: 'var(--glass-blur-nav)',
                }}
            >
                {tabItems.map(({ to, label, Icon }) => {
                    const isActive = currentPath === to
                    return (
                        <Link
                            key={to}
                            to={to}
                            aria-current={isActive ? 'page' : undefined}
                            className="flex-1 flex flex-col items-center justify-center gap-0.5"
                            style={{
                                fontSize: 9,
                                fontWeight: 600,
                                color: isActive ? 'var(--color-accent-text)' : 'var(--color-text-sub)',
                            }}
                        >
                            <Icon size={16} />
                            {label}
                        </Link>
                    )
                })}
                <button
                    ref={moreButtonRef}
                    type="button"
                    aria-expanded={isMoreOpen}
                    aria-controls="mobile-more-sheet"
                    onClick={() => setIsMoreOpen((v) => !v)}
                    className="flex-1 flex flex-col items-center justify-center gap-0.5"
                    style={{
                        fontSize: 9,
                        fontWeight: 600,
                        color: moreActive ? 'var(--color-accent-text)' : 'var(--color-text-sub)',
                    }}
                >
                    <MoreHorizontal size={16} />
                    More
                </button>
            </nav>
        </>
    )
}
