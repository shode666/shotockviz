import { Link, useMatches } from '@tanstack/react-router'
import { LayoutDashboard, TrendingUp, SlidersHorizontal, Briefcase, Bell } from 'lucide-react'

// 5 items per bd:ux-2026-09 decisions — News/Settings live behind the top nav
// on desktop only; mobile keeps the primary trading workflow within thumb reach.
const tabItems = [
    { to: '/dashboard', label: 'Dashboard', Icon: LayoutDashboard },
    { to: '/', label: 'Chart', Icon: TrendingUp },
    { to: '/screener', label: 'Screener', Icon: SlidersHorizontal },
    { to: '/portfolio', label: 'Portfolio', Icon: Briefcase },
    { to: '/alerts', label: 'Alerts', Icon: Bell },
]

export default function MobileTabBar() {
    const matches = useMatches()
    const currentPath = matches[matches.length - 1]?.pathname || '/'

    return (
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
        </nav>
    )
}
