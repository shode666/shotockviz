import { useState, useEffect, useCallback, useRef } from 'react';
import ReactDOM from 'react-dom';
import { useNavigate, useMatchRoute, useRouterState } from '@tanstack/react-router';
import { Plus, GripVertical, Loader2 } from 'lucide-react';
import useAppStore from '@/store/appStore';
import useAuthStore from '@/store/authStore';
import watchlistService from '@/services/watchlistService';
import stockService from '@/services/stockService';
import api from '@/services/api';
import { parseSymbol, MARKET_COLORS } from '@/utils/formatters';
import { WatchlistSearch } from './WatchlistSearch';
import { usePriceUpdates } from '@/hooks/usePriceUpdates';

/** Glass-styled tooltip (hover) — portal to body so it escapes sidebar overflow */
function GlassTooltip({ children, text }: { children: React.ReactNode; text: string }) {
    const [show, setShow] = useState(false);
    const triggerRef = useRef<HTMLDivElement>(null);
    const [pos, setPos] = useState({ top: 0, left: 0 });

    const handleEnter = () => {
        if (triggerRef.current) {
            const rect = triggerRef.current.getBoundingClientRect();
            // Center tooltip vertically with the trigger row, to the right of sidebar
            setPos({ top: rect.top + rect.height / 2, left: rect.right + 8 });
        }
        setShow(true);
    };

    return (
        <div
            ref={triggerRef}
            onMouseEnter={handleEnter}
            onMouseLeave={() => setShow(false)}
        >
            {children}
            {show && ReactDOM.createPortal(
                <div
                    className="glass-tooltip whitespace-pre-line"
                    style={{
                        position: 'fixed',
                        top: pos.top,
                        left: pos.left,
                        transform: 'translateY(-50%)',
                        zIndex: 99999,
                        maxWidth: 320,
                        pointerEvents: 'none',
                    }}
                >
                    {text}
                </div>,
                document.body,
            )}
        </div>
    );
}

/** FGI score → color */
function fgiColor(score: number | null): string {
    if (score == null) return 'var(--color-text-sub)';
    if (score <= 25) return '#ef4444';      // Extreme Fear — red
    if (score <= 45) return '#f97316';      // Fear — orange
    if (score <= 55) return '#eab308';      // Neutral — yellow
    if (score <= 75) return '#22c55e';      // Greed — green
    return '#16a34a';                       // Extreme Greed — bright green
}

const INDICES_SYMS = [
    { key: '^SET', label: 'SET' },
    { key: '^GSPC', label: 'S&P500' },
    { key: '^IXIC', label: 'NASDAQ' },
    { key: '^VIX', label: 'VIX' },
];

// Default symbols to show when user is not authenticated (no fake prices)
// US stocks first, then Thai stocks
const GUEST_SYMBOLS = [
    { sym: 'NVDA', name: 'NVIDIA', price: null, chg: null, pct: null, up: true },
    { sym: 'AAPL', name: 'Apple Inc.', price: null, chg: null, pct: null, up: true },
    { sym: 'TSLA', name: 'Tesla', price: null, chg: null, pct: null, up: true },
    { sym: 'MSFT', name: 'Microsoft', price: null, chg: null, pct: null, up: true },
    { sym: 'GOOGL', name: 'Alphabet', price: null, chg: null, pct: null, up: true },
    { sym: 'AMZN', name: 'Amazon', price: null, chg: null, pct: null, up: true },
    { sym: 'PTT.BK', name: 'ปตท.', price: null, chg: null, pct: null, up: true },
    { sym: 'ADVANC.BK', name: 'แอดวานซ์', price: null, chg: null, pct: null, up: true },
    { sym: 'KBANK.BK', name: 'กสิกรไทย', price: null, chg: null, pct: null, up: true },
    { sym: 'SCB.BK', name: 'ไทยพาณิชย์', price: null, chg: null, pct: null, up: true },
    { sym: 'AOT.BK', name: 'ท่าอากาศยานไทย', price: null, chg: null, pct: null, up: true },
    { sym: 'CPALL.BK', name: 'ซีพีออลล์', price: null, chg: null, pct: null, up: true },
];

export default function Sidebar() {
    const { selectedStock, setSelectedStock, dataVersion } = useAppStore();
    const { isAuthenticated } = useAuthStore();
    const navigate = useNavigate();
    const matchRoute = useMatchRoute();
    const isChart = !!matchRoute({ to: '/' });
    const location = useRouterState({ select: s => s.location.pathname });
    // Pages that handle selectedStock themselves — don't redirect to chart from these
    const STAY_PUT_ROUTES = ['/news', '/screener', '/alerts', '/portfolio', '/dashboard'];

    // Watchlist state
    const [watchlistId, setWatchlistId] = useState(null);
    const [symbols, setSymbols] = useState([]);
    const [names, setNames] = useState<Record<string, { name: string; market?: string | null }>>({});

    // Price polling via shared hook
    const { prices } = usePriceUpdates(symbols, { enabled: isAuthenticated });

    // Indices price polling via same hook (always enabled)
    const indicesSyms = INDICES_SYMS.map(i => i.key);
    const { prices: indicesData } = usePriceUpdates(indicesSyms, { enabled: true });

    // Fear & Greed Index
    const [fgi, setFgi] = useState<{ score: number | null; label: string | null; change: number | null }>({ score: null, label: null, change: null });
    useEffect(() => {
        const fetchFgi = () => {
            api.get('/market/fgi').then(res => setFgi(res.data)).catch(() => {});
        };
        fetchFgi();
        const iv = setInterval(fetchFgi, 5 * 60_000); // refresh every 5 min
        return () => clearInterval(iv);
    }, []);

    // Add-stock UI state
    const [adding, setAdding] = useState(false);

    // Symbols just added this session that don't have a quote yet — shows the
    // "loading price…" spinner row until usePriceUpdates delivers the first
    // quote (bd:ux-2026-09 — Chart mock's just-added watchlist row state).
    const [pendingSyms, setPendingSyms] = useState<Set<string>>(new Set());

    // Symbols currently being deleted (shows spinner, disables button)
    const [deletingSyms, setDeletingSyms] = useState<Set<string>>(new Set());

    // Drag-and-drop reorder state
    const dragSymRef = useRef<string | null>(null);     // symbol being dragged
    const [dragOverSym, setDragOverSym] = useState<string | null>(null); // insertion target
    const reorderTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    // ── Load watchlist ─────────────────────────────────────────────────────────
    const loadWatchlist = useCallback(async () => {
        if (!isAuthenticated) return;
        try {
            const res = await watchlistService.getAll();
            const lists = res.data;
            if (lists.length === 0) {
                const created = await watchlistService.create('My Watchlist');
                setWatchlistId(created.data.id);
                setSymbols([]);
            } else {
                const first = lists[0];
                setWatchlistId(first.id);
                setSymbols(first.items?.map((i) => i.symbol) ?? []);
            }
        } catch { /* ignore */ }
    }, [isAuthenticated]);

    useEffect(() => { loadWatchlist(); }, [loadWatchlist]);

    // ── Fetch company names + market type for watchlist symbols ─────────────────
    useEffect(() => {
        if (!symbols.length) return;
        stockService.getNames(symbols)
            .then((res) => {
                const data = res.data ?? {};
                // API now returns {symbol: {name, market}} — handle both old (string) and new format
                const parsed: Record<string, { name: string; market?: string | null }> = {};
                for (const [sym, val] of Object.entries(data)) {
                    if (typeof val === 'string') {
                        parsed[sym] = { name: val, market: null };
                    } else {
                        parsed[sym] = val as { name: string; market?: string | null };
                    }
                }
                setNames((prev) => ({ ...prev, ...parsed }));
            })
            .catch(() => { /* names are optional — fall back to symbol */ });
    }, [symbols]);

    // ── Handlers ───────────────────────────────────────────────────────────────
    const handleSelect = (sym, name) => {
        const p = prices[sym];
        setSelectedStock({
            sym, name,
            price: p?.price?.toFixed(2) ?? '—',
            chg: p?.change?.toFixed(2) ?? '—',
            pct: p?.change_pct != null ? `${p.change_pct >= 0 ? '+' : ''}${p.change_pct.toFixed(2)}%` : '—',
            up: (p?.change ?? 0) >= 0,
        });
        // Only navigate to chart if not on a page that already uses selectedStock
        if (!STAY_PUT_ROUTES.includes(location)) {
            navigate({ to: '/' });
        }
    };

    const handleAddStock = async (sym: string) => {
        if (!sym || !watchlistId) return;
        try {
            await watchlistService.addStock(watchlistId, sym);
            setSymbols((prev) => (prev.includes(sym) ? prev : [...prev, sym]));
            setPendingSyms((prev) => new Set(prev).add(sym));
        } catch { /* duplicate or error */ }
        setAdding(false);
    };

    // Clear the "just added" pending state once a quote arrives for that symbol
    useEffect(() => {
        setPendingSyms((prev) => {
            if (prev.size === 0) return prev;
            const next = new Set(prev);
            let changed = false;
            for (const sym of prev) {
                if (prices[sym]) { next.delete(sym); changed = true; }
            }
            return changed ? next : prev;
        });
    }, [prices]);

    const handleRemove = async (sym) => {
        if (!watchlistId || deletingSyms.has(sym)) return;

        // Optimistic remove — feels instant
        setSymbols((prev) => prev.filter((s) => s !== sym));
        setDeletingSyms((prev) => new Set(prev).add(sym));
        setPendingSyms((prev) => { if (!prev.has(sym)) return prev; const next = new Set(prev); next.delete(sym); return next; });

        try {
            await watchlistService.removeStock(watchlistId, sym);
        } catch {
            // Rollback on failure
            setSymbols((prev) => [...prev, sym]);
        } finally {
            setDeletingSyms((prev) => { const next = new Set(prev); next.delete(sym); return next; });
        }
    };

    // ── Drag-and-drop reorder ──────────────────────────────────────────────────
    const handleDragStart = (sym: string) => {
        dragSymRef.current = sym;
    };

    const handleDragOver = (e: React.DragEvent, overSym: string) => {
        e.preventDefault(); // allow drop
        if (dragSymRef.current && dragSymRef.current !== overSym) {
            setDragOverSym(overSym);
            // Reorder locally on the fly for instant visual feedback
            setSymbols((prev) => {
                const from = prev.indexOf(dragSymRef.current!);
                const to = prev.indexOf(overSym);
                if (from === -1 || to === -1 || from === to) return prev;
                const next = [...prev];
                next.splice(from, 1);
                next.splice(to, 0, dragSymRef.current!);
                return next;
            });
        }
    };

    const handleDragEnd = () => {
        const sym = dragSymRef.current;
        dragSymRef.current = null;
        setDragOverSym(null);
        if (!sym || !watchlistId) return;

        // Debounce — only persist once dragging stops
        if (reorderTimerRef.current) clearTimeout(reorderTimerRef.current);
        reorderTimerRef.current = setTimeout(() => {
            setSymbols((current) => {
                watchlistService.reorderStocks(watchlistId, current).catch(() => {/* best-effort */});
                return current;
            });
        }, 300);
    };


    const displayList = isAuthenticated
        ? symbols.map((sym) => ({
            sym,
            name: names[sym]?.name || sym,
            market: names[sym]?.market || null,
        }))
        : GUEST_SYMBOLS;

    return (
        <aside
            className="hidden md:flex flex-col overflow-hidden flex-shrink-0"
            aria-label="Watchlist"
            style={{
                width: 264, minWidth: 264,
                background: 'var(--surface-1)',
                backdropFilter: 'var(--glass-blur-nav)',
                WebkitBackdropFilter: 'var(--glass-blur-nav)',
                borderRight: '1px solid var(--color-border)',
            }}
        >
            {/* Header */}
            <div className="flex items-center justify-between px-3 py-2.5 border-b" style={{ borderColor: 'var(--color-border)' }}>
                <span className="text-[10px] font-bold tracking-wider uppercase" style={{ color: 'var(--color-text-sub)' }}>Watchlist</span>
                {isAuthenticated && (
                    <button
                        onClick={() => setAdding((v) => !v)}
                        aria-label="เพิ่มหุ้น"
                        className="flex items-center justify-center rounded-lg transition-colors"
                        style={{ width: 24, height: 24, color: 'var(--color-text-sub)' }}
                        onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--surface-2)'; e.currentTarget.style.color = 'var(--color-text)' }}
                        onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--color-text-sub)' }}
                    >
                        <Plus size={14} />
                    </button>
                )}
            </div>

            {/* Add stock with autocomplete */}
            {adding && (
                <WatchlistSearch
                    onSelect={handleAddStock}
                    onCancel={() => setAdding(false)}
                />
            )}

            {/* Market Indices — real data */}
            <div className="px-3 py-2 border-b" style={{ borderColor: 'var(--color-border)' }}>
                {INDICES_SYMS.map(({ key, label }) => {
                    const q = indicesData[key];
                    const val = q?.price != null ? q.price.toFixed(2) : '—';
                    const chg = q?.change != null ? `${q.change >= 0 ? '+' : ''}${q.change.toFixed(2)}` : '—';
                    const up = (q?.change ?? 0) >= 0;
                    const row = (
                        <div key={key} className="flex justify-between items-center py-0.5">
                            <span className="text-[11px] font-medium" style={{ color: 'var(--color-text-sub)' }}>{label}</span>
                            <div className="text-right">
                                <div className="text-[11px] font-medium tabular-nums">{val}</div>
                                <div className="text-[10px] tabular-nums" style={{ color: up ? 'var(--color-green)' : 'var(--color-red)' }}>{chg}</div>
                            </div>
                        </div>
                    );
                    if (key === '^VIX') return (
                        <GlassTooltip key={key} text={"VIX — ดัชนีความผันผวน (Volatility Index)\nวัดความกลัวของตลาด ยิ่งสูงยิ่งผันผวน\n< 15 สงบ | 15-25 ปกติ | 25-30 ระวัง | > 30 ตื่นกลัว"}>
                            {row}
                        </GlassTooltip>
                    );
                    return row;
                })}
                {/* Fear & Greed Index */}
                <GlassTooltip text={"FGI — Fear & Greed Index (ดัชนีความกลัวและความโลภ)\n0-25 กลัวสุดขีด | 25-45 กลัว | 45-55 เป็นกลาง\n55-75 โลภ | 75-100 โลภสุดขีด"}>
                    <div className="flex justify-between items-center py-0.5">
                        <span className="text-[11px] font-medium" style={{ color: 'var(--color-text-sub)' }}>FGI</span>
                        <div className="text-right">
                            <div className="text-[11px] font-bold tabular-nums" style={{ color: fgiColor(fgi.score) }}>
                                {fgi.score != null ? fgi.score.toFixed(0) : '—'}
                            </div>
                            <div className="text-[10px]" style={{ color: fgiColor(fgi.score) }}>
                                {fgi.label ?? '—'}
                            </div>
                        </div>
                    </div>
                </GlassTooltip>
            </div>

            {/* Stock list */}
            <div className="flex-1 overflow-y-auto">
                {displayList.length === 0 && (
                    <div className="px-3 py-8 text-center text-[11px]" style={{ color: 'var(--color-text-sub)' }}>
                        ยังไม่มีหุ้น<br />กด + เพื่อเพิ่ม
                    </div>
                )}
                {displayList.map((s) => {
                    const q = prices[s.sym];
                    const isActive = selectedStock?.sym === s.sym && isChart;
                    const isFund = s.market === 'FUND' || q?.type === 'fund_nav';
                    const isPending = pendingSyms.has(s.sym) && !q;
                    const up = q ? q.change >= 0 : true;
                    const price = q?.price != null ? q.price.toFixed(2) : '—';
                    const pct = q?.change_pct != null && q.change_pct !== 0
                        ? `${q.change_pct >= 0 ? '+' : ''}${q.change_pct.toFixed(2)}%`
                        : isFund
                            ? (q?.nav_date ? `NAV ${q.nav_date}` : 'NAV')
                            : '';

                    const isDragOver = dragOverSym === s.sym;
                    return (
                        <div
                            key={s.sym}
                            className="group flex items-center transition-all"
                            draggable={isAuthenticated}
                            onDragStart={() => handleDragStart(s.sym)}
                            onDragOver={(e) => handleDragOver(e, s.sym)}
                            onDragEnd={handleDragEnd}
                            style={{
                                minHeight: 'var(--row-h)',
                                background: isActive ? 'var(--surface-3)' : 'transparent',
                                borderRight: isActive ? '2px solid var(--color-accent)' : '2px solid transparent',
                                borderTop: isDragOver ? '2px solid var(--color-accent)' : '2px solid transparent',
                                opacity: dragSymRef.current === s.sym ? 0.4 : 1,
                                cursor: isAuthenticated ? 'grab' : 'default',
                            }}
                        >
                            {/* Drag grip — visible on hover for authenticated users */}
                            {isAuthenticated && (
                                <span
                                    className="pl-1 opacity-0 group-hover:opacity-40 transition-opacity flex-shrink-0"
                                    style={{ color: 'var(--color-text-sub)', cursor: 'grab' }}
                                >
                                    <GripVertical size={11} />
                                </span>
                            )}
                            <button
                                onClick={() => handleSelect(s.sym, s.name)}
                                className="flex-1 flex items-center justify-between px-2 py-2 transition-colors text-left"
                                style={{ cursor: 'pointer' }}
                                onMouseEnter={(e) => { if (!isActive) (e.currentTarget.parentElement as HTMLElement).style.background = 'var(--surface-2)'; }}
                                onMouseLeave={(e) => { if (!isActive) (e.currentTarget.parentElement as HTMLElement).style.background = 'transparent'; }}
                            >
                                <div>
                                    <div className="text-[11px] font-semibold">{parseSymbol(s.sym).display}</div>
                                    <div className="text-[10px] truncate" style={{ maxWidth: 90, color: 'var(--color-text-sub)' }}>
                                        {s.name}{isPending ? ' · เพิ่งเพิ่ม' : ''}
                                    </div>
                                </div>
                                <div className="text-right">
                                    {isPending ? (
                                        <div className="flex items-center gap-1.5 justify-end" style={{ color: 'var(--color-text-sub)' }}>
                                            <span
                                                aria-hidden="true"
                                                style={{
                                                    display: 'inline-block', width: 10, height: 10,
                                                    border: '2px solid var(--color-border-strong)',
                                                    borderTopColor: 'var(--color-accent)',
                                                    borderRadius: '50%',
                                                    animation: 'spin 0.65s linear infinite',
                                                }}
                                            />
                                            <span className="text-[10px]">loading price…</span>
                                        </div>
                                    ) : (
                                        <div className="text-[11px] font-medium" style={{ fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums' }}>{price}</div>
                                    )}
                                    {isPending ? (
                                        <div className="skeleton ml-auto" style={{ width: 34, height: 8, borderRadius: 4 }} />
                                    ) : (
                                        <div className="text-[10px]" style={{ fontFamily: 'var(--font-mono)', fontVariantNumeric: 'tabular-nums', color: (isFund && (!q?.change_pct || q.change_pct === 0)) ? 'var(--color-text-sub)' : (up ? 'var(--color-green)' : 'var(--color-red)') }}>{pct}</div>
                                    )}
                                </div>
                            </button>
                            {isAuthenticated && (
                                <button
                                    onClick={() => handleRemove(s.sym)}
                                    disabled={deletingSyms.has(s.sym)}
                                    className="pr-2 opacity-0 group-hover:opacity-100 transition-opacity"
                                    style={{ color: 'var(--color-text-sub)', cursor: deletingSyms.has(s.sym) ? 'default' : 'pointer' }}
                                >
                                    {deletingSyms.has(s.sym)
                                        ? <Loader2 size={11} className="animate-spin" />
                                        : <span style={{ fontSize: '10px' }}>✕</span>
                                    }
                                </button>
                            )}
                        </div>
                    );
                })}
            </div>

            {/* Add stock footer */}
            <div className="p-3 border-t" style={{ borderColor: 'var(--color-border)' }}>
                <button
                    onClick={() => isAuthenticated ? setAdding(true) : navigate({ to: '/login' })}
                    className="w-full py-2 text-xs rounded-xl transition-all flex items-center justify-center gap-1"
                    style={{ color: 'var(--color-accent)', border: '1px solid color-mix(in srgb, var(--color-accent) 30%, transparent)', background: 'transparent' }}
                    onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-accent-glow)')}
                    onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                >
                    <Plus size={12} />
                    เพิ่มหุ้น
                </button>
            </div>
        </aside>
    );
}
