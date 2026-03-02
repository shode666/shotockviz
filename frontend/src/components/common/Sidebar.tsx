import { useState, useEffect, useCallback, useRef } from 'react';
import { useNavigate, useMatchRoute } from '@tanstack/react-router';
import { Plus, X, Loader2, GripVertical } from 'lucide-react';
import useAppStore from '@/store/appStore';
import useAuthStore from '@/store/authStore';
import watchlistService from '@/services/watchlistService';
import stockService from '@/services/stockService';

const INDICES_SYMS = [
    { key: '^SET', label: 'SET' },
    { key: '^GSPC', label: 'S&P500' },
    { key: '^IXIC', label: 'NASDAQ' },
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

    // Watchlist state
    const [watchlistId, setWatchlistId] = useState(null);
    const [symbols, setSymbols] = useState([]);
    const [prices, setPrices] = useState({});
    const [names, setNames] = useState<Record<string, string>>({});
    const priceTimerRef = useRef(null);
    const retryTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    // Indices state (real data)
    const [indicesData, setIndicesData] = useState({});

    // Add-stock / autocomplete state
    const [adding, setAdding] = useState(false);
    const [searchQuery, setSearchQuery] = useState('');
    const [searchResults, setSearchResults] = useState([]);
    const [searchLoading, setSearchLoading] = useState(false);
    const searchTimerRef = useRef(null);

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

    // ── Fetch company names for watchlist symbols ──────────────────────────────
    useEffect(() => {
        if (!symbols.length) return;
        stockService.getNames(symbols)
            .then((res) => setNames((prev) => ({ ...prev, ...res.data })))
            .catch(() => { /* names are optional — fall back to symbol */ });
    }, [symbols]);

    // ── Refresh live prices — sequential queue, auto-retries on 202 ────────────
    const refreshPrices = useCallback(async () => {
        if (!isAuthenticated) return;   // guests see static symbol list, no price fetching
        const syms = symbols;
        if (!syms.length) return;
        // Cancel any pending retry — this run supersedes it
        if (retryTimerRef.current) { clearTimeout(retryTimerRef.current); retryTimerRef.current = null; }
        let anyMissing = false;
        for (const s of syms) {
            try {
                const r = await stockService.getQuote(s);
                if (r.data) setPrices((prev) => ({ ...prev, [s]: r.data }));
                else anyMissing = true;   // 202 — backend still warming cache
            } catch { anyMissing = true; }
        }
        // If any symbols still pending, retry in 8s (cache filling up)
        if (anyMissing) {
            retryTimerRef.current = setTimeout(() => refreshPricesRef.current(), 8000);
        }
    }, [symbols, isAuthenticated]);

    // Keep a ref to the latest refreshPrices so the interval never needs to be recreated
    const refreshPricesRef = useRef(refreshPrices);
    useEffect(() => { refreshPricesRef.current = refreshPrices; }, [refreshPrices]);

    // Interval set up ONCE — calls the ref so it always uses the latest symbols/auth state
    useEffect(() => {
        priceTimerRef.current = setInterval(() => refreshPricesRef.current(), 60000);
        return () => {
            clearInterval(priceTimerRef.current);
            if (retryTimerRef.current) clearTimeout(retryTimerRef.current);
        };
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    // Immediate fetch when symbols/auth change OR when backend cache becomes ready
    useEffect(() => {
        refreshPricesRef.current();
    }, [refreshPrices, dataVersion]);

    // ── Fetch real index quotes — sequential queue ─────────────────────────────
    const refreshIndices = useCallback(async () => {
        for (const { key } of INDICES_SYMS) {
            try {
                const r = await stockService.getQuote(key);
                if (r.data) setIndicesData((prev) => ({ ...prev, [key]: r.data }));
            } catch { /* ignore */ }
        }
    }, []);

    const refreshIndicesRef = useRef(refreshIndices);
    // Interval set up ONCE for indices (60 s)
    useEffect(() => {
        const t = setInterval(() => refreshIndicesRef.current(), 60_000);
        return () => clearInterval(t);
    }, []); // eslint-disable-line react-hooks/exhaustive-deps

    // Immediate fetch on mount or when backend cache becomes ready
    useEffect(() => {
        refreshIndicesRef.current();
    }, [dataVersion]);

    // ── Autocomplete search (debounced 300 ms) ────────────────────────────────
    useEffect(() => {
        if (!searchQuery.trim()) {
            setSearchResults([]);
            return;
        }
        setSearchLoading(true);
        clearTimeout(searchTimerRef.current);
        searchTimerRef.current = setTimeout(async () => {
            try {
                const res = await stockService.search(searchQuery);
                setSearchResults(res.data?.results ?? res.data ?? []);
            } catch {
                setSearchResults([]);
            } finally {
                setSearchLoading(false);
            }
        }, 300);
        return () => clearTimeout(searchTimerRef.current);
    }, [searchQuery]);

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
        navigate({ to: '/' });
    };

    const handleAddStock = async (sym?: string) => {
        const s = sym ?? searchQuery.trim().toUpperCase();
        if (!s || !watchlistId) return;
        try {
            await watchlistService.addStock(watchlistId, s);
            setSymbols((prev) => (prev.includes(s) ? prev : [...prev, s]));
            // If the name came from a search result, cache it immediately
            const hit = searchResults.find((r) => r.symbol === s);
            if (hit) {
                setNames((prev) => ({ ...prev, [s]: hit.name_th || hit.name || s }));
            }
        } catch { /* duplicate or error */ }
        setSearchQuery('');
        setSearchResults([]);
        setAdding(false);
    };

    const handleRemove = async (sym) => {
        if (!watchlistId || deletingSyms.has(sym)) return;

        // Optimistic remove — feels instant
        setSymbols((prev) => prev.filter((s) => s !== sym));
        setDeletingSyms((prev) => new Set(prev).add(sym));

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

    const cancelAdding = () => {
        setAdding(false);
        setSearchQuery('');
        setSearchResults([]);
    };

    const displayList = isAuthenticated
        ? symbols.map((sym) => ({ sym, name: names[sym] || sym }))
        : GUEST_SYMBOLS;

    return (
        <aside className="panel border-r flex flex-col overflow-hidden" style={{ width: 220, minWidth: 220, borderRightWidth: 1, borderRightStyle: 'solid', borderRightColor: 'var(--color-border)' }}>
            {/* Header */}
            <div className="flex items-center justify-between px-3 py-2.5 border-b" style={{ borderColor: 'var(--color-border)' }}>
                <span className="text-[10px] font-semibold tracking-wider uppercase" style={{ color: 'var(--color-text-sub)' }}>Watchlist</span>
                {isAuthenticated && (
                    <button onClick={() => setAdding((v) => !v)} className="p-0.5 rounded hover:bg-[var(--color-hover)] transition-colors" style={{ color: 'var(--color-accent)' }}>
                        <Plus size={14} />
                    </button>
                )}
            </div>

            {/* Add stock with autocomplete */}
            {adding && (
                <div className="relative border-b" style={{ borderColor: 'var(--color-border)' }}>
                    <div className="px-3 py-2 flex gap-1 items-center">
                        <div className="relative flex-1">
                            <input
                                autoFocus
                                className="input-field text-xs py-1 w-full pr-6"
                                placeholder="PTT.BK, AAPL..."
                                value={searchQuery}
                                onChange={(e) => setSearchQuery(e.target.value)}
                                onKeyDown={(e) => {
                                    if (e.key === 'Enter') handleAddStock();
                                    if (e.key === 'Escape') cancelAdding();
                                }}
                            />
                            {searchLoading && (
                                <Loader2 size={11} className="absolute right-2 top-1/2 -translate-y-1/2 animate-spin" style={{ color: 'var(--color-text-sub)' }} />
                            )}
                        </div>
                        <button onClick={cancelAdding} className="p-1 rounded hover:bg-[var(--color-hover)] transition-colors" style={{ color: 'var(--color-text-sub)' }}>
                            <X size={12} />
                        </button>
                    </div>

                    {/* Autocomplete dropdown */}
                    {/* Show "add directly" button when: query typed, not loading, search returned empty */}
                    {searchQuery.trim() && !searchLoading && searchResults.length === 0 && (
                        <div
                            className="glass-dropdown absolute left-0 right-0 z-50 rounded-b-xl overflow-hidden"
                            style={{ top: '100%' }}
                        >
                            <button
                                onClick={() => handleAddStock(searchQuery.trim().toUpperCase())}
                                className="w-full flex items-center gap-2 px-3 py-2.5 text-left transition-colors hover:bg-[var(--color-hover)]"
                            >
                                <Plus size={12} style={{ color: 'var(--color-accent)', flexShrink: 0 }} />
                                <div>
                                    <div className="text-[11px] font-semibold" style={{ color: 'var(--color-text)' }}>
                                        เพิ่ม {searchQuery.trim().toUpperCase()} โดยตรง
                                    </div>
                                    <div className="text-[10px]" style={{ color: 'var(--color-text-sub)', opacity: 0.7 }}>
                                        ไม่พบในฐานข้อมูล · เพิ่มด้วย ticker โดยตรง
                                    </div>
                                </div>
                            </button>
                        </div>
                    )}
                    {searchResults.length > 0 && (
                        <div
                            className="glass-dropdown absolute left-0 right-0 z-50 rounded-b-xl overflow-hidden"
                            style={{ top: '100%' }}
                        >
                            {searchResults.slice(0, 6).map((r) => (
                                <button
                                    key={r.symbol}
                                    onClick={() => handleAddStock(r.symbol)}
                                    className="w-full flex items-center justify-between px-3 py-2 text-left transition-colors hover:bg-[var(--color-hover)]"
                                >
                                    <div className="flex-1 min-w-0">
                                        <div className="text-[11px] font-semibold" style={{ color: 'var(--color-text)' }}>{r.symbol}</div>
                                        <div className="text-[10px] truncate" style={{ color: 'var(--color-text-sub)', maxWidth: 120 }}>
                                            {r.name_th || r.name}
                                        </div>
                                    </div>
                                    <span
                                        className="badge text-[9px] ml-2 flex-shrink-0"
                                        style={{
                                            background: r.market === 'FUND'
                                                ? 'rgba(251,191,36,0.15)'
                                                : r.market === 'SET'
                                                    ? 'rgba(52,211,153,0.15)'
                                                    : 'rgba(124,92,252,0.15)',
                                            color: r.market === 'FUND'
                                                ? 'var(--color-yellow)'
                                                : r.market === 'SET'
                                                    ? 'var(--color-green)'
                                                    : 'var(--color-accent)',
                                        }}
                                    >
                                        {r.market || 'US'}
                                    </span>
                                </button>
                            ))}
                        </div>
                    )}
                </div>
            )}

            {/* Market Indices — real data */}
            <div className="px-3 py-2 border-b" style={{ borderColor: 'var(--color-border)' }}>
                {INDICES_SYMS.map(({ key, label }) => {
                    const q = indicesData[key];
                    const val = q?.price != null ? q.price.toFixed(2) : '—';
                    const chg = q?.change != null ? `${q.change >= 0 ? '+' : ''}${q.change.toFixed(2)}` : '—';
                    const up = (q?.change ?? 0) >= 0;
                    return (
                        <div key={key} className="flex justify-between items-center py-0.5">
                            <span className="text-[11px] font-medium" style={{ color: 'var(--color-text-sub)' }}>{label}</span>
                            <div className="text-right">
                                <div className="text-[11px] font-medium tabular-nums">{val}</div>
                                <div className="text-[10px] tabular-nums" style={{ color: up ? 'var(--color-green)' : 'var(--color-red)' }}>{chg}</div>
                            </div>
                        </div>
                    );
                })}
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
                    const up = q ? q.change >= 0 : true;
                    const price = q?.price != null ? q.price.toFixed(2) : '—';
                    const pct = q?.change_pct != null
                        ? `${q.change_pct >= 0 ? '+' : ''}${q.change_pct.toFixed(2)}%`
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
                                background: isActive
                                    ? 'color-mix(in srgb, var(--color-accent) 8%, transparent)'
                                    : 'transparent',
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
                                className="flex-1 flex items-center justify-between px-2 py-2.5 transition-colors text-left"
                                style={{ cursor: 'pointer' }}
                                onMouseEnter={(e) => { if (!isActive) (e.currentTarget.parentElement as HTMLElement).style.background = 'var(--color-hover)'; }}
                                onMouseLeave={(e) => { if (!isActive) (e.currentTarget.parentElement as HTMLElement).style.background = 'transparent'; }}
                            >
                                <div>
                                    <div className="text-[11px] font-semibold">{s.sym.replace('.BK', '')}</div>
                                    <div className="text-[10px] truncate" style={{ maxWidth: 80, color: 'var(--color-text-sub)' }}>{s.name}</div>
                                </div>
                                <div className="text-right">
                                    <div className="text-[11px] font-medium tabular-nums">{price}</div>
                                    <div className="text-[10px] tabular-nums" style={{ color: up ? 'var(--color-green)' : 'var(--color-red)' }}>{pct}</div>
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
                                        : <X size={11} />
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
