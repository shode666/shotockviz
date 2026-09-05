import { useState, useRef, useEffect } from 'react'
import { Link, useMatches, useNavigate } from '@tanstack/react-router'
import {
    Search, Sun, Moon, LogOut, Settings, Command,
    TrendingUp, SlidersHorizontal, Briefcase, Bell, Newspaper, LayoutDashboard,
} from 'lucide-react'
import useAppStore from '@/store/appStore'
import useAuthStore from '@/store/authStore'
import ShotockLogo from './ShotockLogo'
import { getSetStatus, getUsStatus, type MarketStatusResult } from '@/utils/marketStatus'

const navItems = [
    { to: '/dashboard', label: 'Dashboard', Icon: LayoutDashboard },
    { to: '/', label: 'Chart', Icon: TrendingUp },
    { to: '/screener', label: 'Screener', Icon: SlidersHorizontal },
    { to: '/portfolio', label: 'Portfolio', Icon: Briefcase },
    { to: '/alerts', label: 'Alerts', Icon: Bell },
    { to: '/news', label: 'News', Icon: Newspaper },
]

const STATUS_COLORS: Record<MarketStatusResult['color'], string> = {
    green: 'var(--color-green)',
    yellow: '#f59e0b',
    gray: 'var(--color-text-sub)',
}

function MarketBadge({ status }: { status: MarketStatusResult }) {
    const dotColor = STATUS_COLORS[status.color]
    return (
        <div className="flex items-center gap-1 text-xs">
            <span
                className={status.pulse ? 'w-1.5 h-1.5 rounded-full animate-pulse-dot' : 'w-1.5 h-1.5 rounded-full'}
                style={{ background: dotColor }}
            />
            <span style={{ color: dotColor }}>{status.label}</span>
        </div>
    )
}

export default function Navbar() {
    const { theme, toggleTheme, setSearchOpen } = useAppStore()
    const { user, isAuthenticated, isLoading, logout } = useAuthStore()
    const matches = useMatches()
    const currentPath = matches[matches.length - 1]?.pathname || '/'
    const navigate = useNavigate()

    const [isDropdownOpen, setIsDropdownOpen] = useState(false)
    const dropdownRef = useRef<HTMLDivElement>(null)

    const [setStatus, setSetStatus] = useState<MarketStatusResult>(getSetStatus)
    const [usStatus, setUsStatus] = useState<MarketStatusResult>(getUsStatus)

    // Refresh market status every 60 s
    useEffect(() => {
        const t = setInterval(() => {
            setSetStatus(getSetStatus())
            setUsStatus(getUsStatus())
        }, 60_000)
        return () => clearInterval(t)
    }, [])

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(event.target as Node)) {
                setIsDropdownOpen(false)
            }
        }
        document.addEventListener('mousedown', handleClickOutside)
        return () => document.removeEventListener('mousedown', handleClickOutside)
    }, [])

    const handleLogout = async () => {
        await logout()
        setIsDropdownOpen(false)
        navigate({ to: '/login' })
    }

    return (
        <>
            <nav
                className="hidden md:flex items-center px-4 gap-5 border-b flex-shrink-0"
                // bd:ux-2026-09 user-reported regression — account-dropdown bled through
                // by the chart canvas on the Chart page. Root cause verified via
                // elementFromPoint() at the geometric overlap between the dropdown
                // (bottom edge ~y139) and TradingChart's <canvas> (top edge ~y127,
                // fixed regardless of viewport height): `backdropFilter` on THIS <nav>
                // creates its own stacking context, so the dropdown's `z-50` only wins
                // comparisons *inside* that context — from the root stacking context,
                // the whole Navbar paints at the implicit "auto" layer (same class as
                // z-index:0/static content) while lightweight-charts' canvases (their
                // own z-index:1/2, same trick as [Q-UX1] commit 80f0d7d) sit in the
                // *positive* z-index paint layer, which always wins regardless of DOM
                // order. Bumping the dropdown's own z-index further would not help —
                // it already wins locally. Elevating the trapping context (this <nav>)
                // above every z-index used inside chart components (max observed: 20,
                // ChartPage.tsx RightPanel toggle) is what actually fixes it.
                style={{
                    height: 48,
                    position: 'relative',
                    zIndex: 30,
                    background: 'var(--surface-1)',
                    backdropFilter: 'var(--glass-blur-nav)',
                    WebkitBackdropFilter: 'var(--glass-blur-nav)',
                    borderColor: 'var(--color-border)',
                    boxShadow: 'var(--glass-inset-edge)',
                }}
            >
                <div className="flex items-center gap-6">
                    {/* Logo */}
                    <div className="flex items-center gap-2.5">
                        <ShotockLogo variant="navbar" className="w-8 h-8 rounded-[11px] shadow-[0_4px_16px_rgba(168,85,247,0.2)] dark:shadow-[0_4px_16px_rgba(168,85,247,0.15)]" />
                        <div className="text-4xl tracking-tight flex items-baseline select-none">
                            <div className="font-extrabold tracking-tight text-gray-900 dark:text-white">S</div>
                            <div
                                className="font-semibold tracking-[-.15em] text-orange-500 dark:text-violet-300 w-2 -translate-x-2 text-xl"
                                style={{ textShadow: 'var(--ho-glow, none)' }}
                            >ho</div>
                            <div className="font-extrabold tracking-tight text-gray-900 dark:text-white">tock</div>
                            <div className="font-semibold text-orange-500 dark:text-violet-300 ml-1"
                                style={{ textShadow: 'var(--ho-glow, none)' }}
                            >Viz</div>
                        </div>
                    </div>

                    {/* Navigation */}
                    <div className="flex items-center gap-1">
                        {navItems.map(({ to, label, Icon }) => {
                            const isActive = currentPath === to
                            return (
                                <Link
                                    key={to}
                                    to={to}
                                    aria-current={isActive ? 'page' : undefined}
                                    className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg text-[11px] font-semibold transition-colors"
                                    style={{
                                        background: isActive ? 'var(--surface-3)' : 'transparent',
                                        color: isActive ? 'var(--color-text)' : 'var(--color-text-sub)',
                                        boxShadow: isActive ? 'inset 0 -2px 0 var(--color-accent)' : 'none',
                                    }}
                                    onMouseEnter={(e) => { if (!isActive) e.currentTarget.style.background = 'var(--surface-2)' }}
                                    onMouseLeave={(e) => { if (!isActive) e.currentTarget.style.background = 'transparent' }}
                                >
                                    <Icon size={13} />
                                    {label}
                                </Link>
                            )
                        })}
                    </div>
                </div>

                <div className="ml-auto flex items-center gap-3">
                    {/* Search */}
                    <button
                        onClick={() => setSearchOpen(true)}
                        className="flex items-center gap-2 px-3 rounded-lg text-[11px] border transition-colors"
                        style={{ height: 30, background: 'var(--surface-1)', borderColor: 'var(--color-border)', color: 'var(--color-text-sub)' }}
                    >
                        <Search size={12} />
                        <span className="flex items-center gap-0.5">
                            ค้นหา PTT, AAPL...
                            <Command size={12} strokeWidth={2} aria-hidden="true" />K
                        </span>
                    </button>

                    {/* Market Status — dynamic */}
                    <div className="flex items-center gap-3 border-l border-r px-3" style={{ borderColor: 'var(--color-border)' }}>
                        <MarketBadge status={setStatus} />
                        <MarketBadge status={usStatus} />
                    </div>

                    {/* Theme Toggle */}
                    <button
                        onClick={toggleTheme}
                        aria-label="สลับธีม"
                        className="flex items-center justify-center rounded-lg border transition-colors"
                        style={{ width: 30, height: 30, background: 'var(--surface-1)', borderColor: 'var(--color-border)', color: 'var(--color-text-sub)' }}
                        onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-2)'; e.currentTarget.style.color = 'var(--color-text)' }}
                        onMouseLeave={(e) => { e.currentTarget.style.background = 'var(--surface-1)'; e.currentTarget.style.color = 'var(--color-text-sub)' }}
                    >
                        {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
                    </button>

                    {/* Settings */}
                    <Link
                        to="/settings"
                        aria-label="ตั้งค่า"
                        aria-current={currentPath === '/settings' ? 'page' : undefined}
                        className="flex items-center justify-center rounded-lg border transition-colors"
                        style={{
                            width: 30, height: 30, background: 'var(--surface-1)',
                            borderColor: currentPath === '/settings' ? 'var(--color-accent)' : 'var(--color-border)',
                            color: currentPath === '/settings' ? 'var(--color-accent-text)' : 'var(--color-text-sub)',
                        }}
                        onMouseEnter={(e) => { if (currentPath !== '/settings') { e.currentTarget.style.background = 'var(--surface-2)'; e.currentTarget.style.color = 'var(--color-text)' } }}
                        onMouseLeave={(e) => { if (currentPath !== '/settings') { e.currentTarget.style.background = 'var(--surface-1)'; e.currentTarget.style.color = 'var(--color-text-sub)' } }}
                    >
                        <Settings size={14} />
                    </Link>

                    {/* Auth */}
                    {isLoading ? (
                        /* Spinner while checkAuth retries — prevents "Login" flash */
                        <div
                            className="w-7 h-7 rounded-full flex items-center justify-center"
                            style={{ background: 'var(--color-hover)' }}
                        >
                            <span
                                style={{
                                    display: 'inline-block',
                                    width: 14, height: 14,
                                    border: '2px solid var(--color-border)',
                                    borderTopColor: 'var(--color-accent)',
                                    borderRadius: '50%',
                                    animation: 'spin 0.65s linear infinite',
                                }}
                            />
                        </div>
                    ) : isAuthenticated ? (
                        <div className="relative" ref={dropdownRef}>
                            <button
                                onClick={() => setIsDropdownOpen(!isDropdownOpen)}
                                className="w-7 h-7 rounded-full flex items-center justify-center text-[11px] font-bold text-white hover:opacity-90 transition-opacity"
                                // bd:ux-2026-09 Chris review — the #7c5cfc/#a855f7 gradient measured
                                // 4.38:1 / 3.96:1 for white text (axe misses gradients). Solid
                                // --color-accent-strong is the same 6.00:1 token .btn-accent already
                                // uses for this exact class of failure (styles.css:529-533).
                                style={{ background: 'var(--color-accent-strong)' }}
                            >
                                {user?.display_name?.[0]?.toUpperCase() || 'U'}
                            </button>

                            {isDropdownOpen && (
                                <div
                                    className="glass-dropdown absolute right-0 mt-2 w-48 z-50"
                                >
                                    <div className="px-4 py-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
                                        <p className="text-sm font-medium" style={{ color: 'var(--color-text)' }}>{user?.display_name}</p>
                                        <p className="text-xs truncate" style={{ color: 'var(--color-text-sub)' }}>{user?.email}</p>
                                    </div>
                                    <div className="p-1">
                                        <button
                                            onClick={handleLogout}
                                            className="w-full flex items-center gap-2 px-3 py-2 text-xs rounded-lg transition-colors hover:bg-red-500/10 text-red-500"
                                        >
                                            <LogOut size={14} />
                                            Logout
                                        </button>
                                    </div>
                                </div>
                            )}
                        </div>
                    ) : (
                        <Link to="/login" className="btn-accent text-[11px] px-3 py-1.5">Login</Link>
                    )}
                </div>
            </nav>
        </>
    )
}
