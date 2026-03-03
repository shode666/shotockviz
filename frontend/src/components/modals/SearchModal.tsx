import { useState, useEffect, useRef, useCallback } from 'react';
import { useNavigate } from '@tanstack/react-router';
import { Search, Clock, X, TrendingUp, Star, ArrowRight, Zap } from 'lucide-react';
import useAppStore from '@/store/appStore';
import stockService from '@/services/stockService';
import { parseSymbol, MARKET_COLORS } from '@/utils/formatters';

// ── Local-storage helpers ─────────────────────────────────────────────────────
const RECENT_KEY = 'shotock_recent_searches';
const MAX_RECENT = 6;

function loadRecent(): SearchResult[] {
    try { return JSON.parse(localStorage.getItem(RECENT_KEY) || '[]'); }
    catch { return []; }
}
function saveRecent(items: SearchResult[]) {
    try { localStorage.setItem(RECENT_KEY, JSON.stringify(items.slice(0, MAX_RECENT))); }
    catch {}
}

// ── Popular defaults shown when search is empty ───────────────────────────────
const POPULAR: SearchResult[] = [
    { symbol: 'PTT.BK',  name: 'ปตท.',            market: 'SET' },
    { symbol: 'KBANK.BK',name: 'กสิกรไทย',        market: 'SET' },
    { symbol: 'NVDA',    name: 'NVIDIA',            market: 'US'  },
    { symbol: 'AAPL',    name: 'Apple Inc.',        market: 'US'  },
    { symbol: '7203.T',  name: 'Toyota Motor',      market: 'JP'  },
    { symbol: '0700.HK', name: 'Tencent',           market: 'HK'  },
];

interface SearchResult {
    symbol: string;
    name: string;
    name_th?: string;
    market?: string;
}

type MarketFilter = 'ALL' | 'SET' | 'US' | 'FUND' | 'JP' | 'HK' | 'UK' | 'CN' | 'DE' | 'KR';

// ── Market badge config (uses MARKET_COLORS from formatters + extras) ────────
const MARKET_META: Record<string, { bg: string; color: string; label: string }> = {
    SET:  { bg: 'rgba(52,211,153,0.15)',  color: 'var(--color-green)',  label: 'SET'  },
    US:   { bg: 'rgba(124,92,252,0.15)',  color: 'var(--color-accent)', label: 'US'   },
    FUND: { bg: 'rgba(251,191,36,0.15)', color: 'var(--color-yellow)', label: 'FUND' },
    IDX:  { bg: 'rgba(96,165,250,0.15)', color: 'var(--color-blue)',   label: 'IDX'  },
    JP:   { bg: 'rgba(248,113,113,0.15)', color: '#f87171',            label: 'JP'   },
    CN:   { bg: 'rgba(251,146,60,0.15)',  color: '#fb923c',            label: 'CN'   },
    HK:   { bg: 'rgba(251,146,60,0.15)',  color: '#fb923c',            label: 'HK'   },
    UK:   { bg: 'rgba(96,165,250,0.15)',  color: '#60a5fa',            label: 'UK'   },
    DE:   { bg: 'rgba(96,165,250,0.15)',  color: '#60a5fa',            label: 'DE'   },
    FR:   { bg: 'rgba(96,165,250,0.15)',  color: '#60a5fa',            label: 'FR'   },
    KR:   { bg: 'rgba(248,113,113,0.15)', color: '#f87171',            label: 'KR'   },
};

function getMarketMeta(market?: string) {
    if (!market) return MARKET_META['US'];
    return MARKET_META[market] ?? MARKET_META['US'];
}

// ── Filter pills ──────────────────────────────────────────────────────────────
const FILTERS: { key: MarketFilter; label: string }[] = [
    { key: 'ALL',  label: 'ทั้งหมด' },
    { key: 'SET',  label: 'หุ้นไทย'  },
    { key: 'US',   label: 'หุ้น US'  },
    { key: 'FUND', label: 'กองทุน'   },
];

// ── Skeleton row ──────────────────────────────────────────────────────────────
function SkeletonRow() {
    return (
        <div className="flex items-center gap-3 px-5 py-3">
            <div className="skeleton w-12 h-4 rounded-md" />
            <div className="skeleton flex-1 h-3 rounded-md" />
            <div className="skeleton w-10 h-5 rounded-full" />
        </div>
    );
}

// ── Result row ────────────────────────────────────────────────────────────────
function ResultRow({
    item,
    isHighlighted,
    onSelect,
    onMouseEnter,
}: {
    item: SearchResult;
    isHighlighted: boolean;
    onSelect: (item: SearchResult) => void;
    onMouseEnter: () => void;
}) {
    const m = getMarketMeta(item.market);
    return (
        <button
            onClick={() => onSelect(item)}
            onMouseEnter={onMouseEnter}
            className="w-full flex items-center gap-3 px-5 py-3 text-left transition-all cursor-pointer group"
            style={{
                background: isHighlighted ? 'var(--color-hover)' : 'transparent',
                borderLeft: isHighlighted ? '2px solid var(--color-accent)' : '2px solid transparent',
            }}
        >
            {/* Symbol + name */}
            <div className="flex-1 min-w-0">
                <div className="flex items-baseline gap-2">
                    <span className="text-sm font-bold tracking-wide" style={{ color: 'var(--color-accent)' }}>
                        {parseSymbol(item.symbol, item.market).display}
                    </span>
                    <span className="text-xs truncate" style={{ color: 'var(--color-text-sub)' }}>
                        {item.name_th || item.name}
                    </span>
                </div>
                {item.name_th && item.name && (
                    <div className="text-[10px] truncate mt-0.5" style={{ color: 'var(--color-text-sub)', opacity: 0.6 }}>
                        {item.name}
                    </div>
                )}
            </div>

            {/* Market badge */}
            <span
                className="text-[10px] font-semibold px-2 py-0.5 rounded-full flex-shrink-0"
                style={{ background: m.bg, color: m.color }}
            >
                {item.market || parseSymbol(item.symbol).market}
            </span>

            {/* Arrow (visible on hover/highlight) */}
            <ArrowRight
                size={13}
                className="flex-shrink-0 transition-opacity"
                style={{
                    color: 'var(--color-accent)',
                    opacity: isHighlighted ? 1 : 0,
                }}
            />
        </button>
    );
}

// ── Main component ────────────────────────────────────────────────────────────
export default function SearchModal() {
    const { searchOpen, setSearchOpen, setSelectedStock } = useAppStore();
    const navigate = useNavigate();

    const [query, setQuery]           = useState('');
    const [results, setResults]       = useState<SearchResult[]>([]);
    const [loading, setLoading]       = useState(false);
    const [filter, setFilter]         = useState<MarketFilter>('ALL');
    const [highlighted, setHighlighted] = useState(0);
    const [recent, setRecent]         = useState<SearchResult[]>([]);

    const inputRef = useRef<HTMLInputElement>(null);
    const listRef  = useRef<HTMLDivElement>(null);
    const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    // Global Cmd/Ctrl+K
    useEffect(() => {
        const handler = (e: KeyboardEvent) => {
            if ((e.metaKey || e.ctrlKey) && e.key === 'k') {
                e.preventDefault();
                setSearchOpen(!searchOpen);
            }
            if (e.key === 'Escape') setSearchOpen(false);
        };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, [searchOpen, setSearchOpen]);

    // On open: focus + reset
    useEffect(() => {
        if (searchOpen) {
            setTimeout(() => inputRef.current?.focus(), 80);
            setQuery('');
            setResults([]);
            setHighlighted(0);
            setRecent(loadRecent());
        }
    }, [searchOpen]);

    // Debounced search
    useEffect(() => {
        if (timerRef.current) clearTimeout(timerRef.current);
        if (query.length < 1) { setResults([]); setLoading(false); return; }
        setLoading(true);
        timerRef.current = setTimeout(async () => {
            try {
                const { data } = await stockService.search(query);
                setResults(Array.isArray(data) ? data : []);
            } catch {
                setResults([]);
            }
            setLoading(false);
            setHighlighted(0);
        }, 280);
    }, [query]);

    // Displayed items (filtered)
    const displayItems: SearchResult[] = query.length > 0
        ? (filter === 'ALL' ? results : results.filter(r => r.market === filter))
        : [];

    const showPopular = query.length === 0;
    const showRecent  = query.length === 0 && recent.length > 0;

    const totalItems = showPopular
        ? (showRecent ? recent.length : POPULAR.length)
        : displayItems.length;

    // Keyboard navigation
    useEffect(() => {
        if (!searchOpen) return;
        const handler = (e: KeyboardEvent) => {
            if (e.key === 'ArrowDown') {
                e.preventDefault();
                setHighlighted(h => Math.min(h + 1, totalItems - 1));
            } else if (e.key === 'ArrowUp') {
                e.preventDefault();
                setHighlighted(h => Math.max(h - 1, 0));
            } else if (e.key === 'Enter') {
                const items = showPopular
                    ? (showRecent ? recent : POPULAR)
                    : displayItems;
                if (items[highlighted]) handleSelect(items[highlighted]);
            }
        };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, [searchOpen, highlighted, totalItems, displayItems, recent, showPopular, showRecent]);

    // Scroll highlighted into view
    useEffect(() => {
        const el = listRef.current?.children[highlighted] as HTMLElement | undefined;
        el?.scrollIntoView({ block: 'nearest' });
    }, [highlighted]);

    const handleSelect = useCallback((item: SearchResult) => {
        setSelectedStock({
            sym: item.symbol,
            name: item.name_th || item.name,
            price: '—', chg: '—', pct: '—', up: true,
        });
        // Save to recent
        const next = [item, ...loadRecent().filter(r => r.symbol !== item.symbol)];
        saveRecent(next);
        setSearchOpen(false);
        navigate({ to: '/' });
    }, [setSelectedStock, setSearchOpen, navigate]);

    const clearRecent = (e: React.MouseEvent) => {
        e.stopPropagation();
        localStorage.removeItem(RECENT_KEY);
        setRecent([]);
    };

    if (!searchOpen) return null;

    return (
        <div
            className="glass-backdrop fixed inset-0 z-50 flex items-start justify-center pt-20"
            onClick={() => setSearchOpen(false)}
        >
            {/* ── Glass panel ─────────────────────────────────────────────── */}
            <div
                className="glass-search w-full max-w-xl glass-slide-up overflow-hidden"
                onClick={e => e.stopPropagation()}
            >
                {/* ── Input row ────────────────────────────────────────────── */}
                <div className="search-input-row flex items-center gap-3 px-4 py-3.5">
                    <Search size={16} className="flex-shrink-0" style={{ color: 'var(--color-accent)' }} />
                    <input
                        ref={inputRef}
                        type="text"
                        value={query}
                        onChange={e => { setQuery(e.target.value); setHighlighted(0); }}
                        placeholder="ค้นหา หุ้น กองทุน เช่น PTT, AAPL, KBANK..."
                        className="flex-1 bg-transparent outline-none text-sm"
                        style={{ color: 'var(--color-text)' }}
                    />
                    {/* Loading spinner */}
                    {loading && (
                        <span className="search-spinner" />
                    )}
                    {/* Clear / ESC badge */}
                    {query ? (
                        <button
                            onClick={() => setQuery('')}
                            className="p-1 rounded-md transition-colors"
                            style={{ color: 'var(--color-text-sub)' }}
                            onMouseEnter={e => (e.currentTarget.style.background = 'var(--color-hover)')}
                            onMouseLeave={e => (e.currentTarget.style.background = 'transparent')}
                        >
                            <X size={13} />
                        </button>
                    ) : (
                        <kbd className="search-kbd">ESC</kbd>
                    )}
                </div>

                {/* ── Filter tabs (only when typing) ───────────────────────── */}
                {query.length > 0 && (
                    <div
                        className="flex gap-1.5 px-4 pb-2.5"
                        style={{ borderBottom: '1px solid var(--search-divider)' }}
                    >
                        {FILTERS.map(f => (
                            <button
                                key={f.key}
                                onClick={() => { setFilter(f.key); setHighlighted(0); }}
                                className="text-xs px-3 py-1 rounded-full font-medium transition-all cursor-pointer"
                                style={filter === f.key
                                    ? { background: 'var(--color-accent)', color: '#fff' }
                                    : { background: 'var(--color-hover)', color: 'var(--color-text-sub)' }
                                }
                            >
                                {f.label}
                            </button>
                        ))}
                    </div>
                )}

                {/* Divider under input (when no filter tabs) */}
                {query.length === 0 && (
                    <div style={{ height: 1, background: 'var(--search-divider)' }} />
                )}

                {/* ── Results area ─────────────────────────────────────────── */}
                <div ref={listRef} className="search-results overflow-y-auto" style={{ maxHeight: 360 }}>

                    {/* Loading skeletons */}
                    {loading && [0, 1, 2].map(i => <SkeletonRow key={i} />)}

                    {/* Search results */}
                    {!loading && query.length > 0 && displayItems.length > 0 && (
                        <>
                            <div className="search-section-label px-5 pt-3 pb-1 flex items-center gap-1.5">
                                <Zap size={10} style={{ color: 'var(--color-accent)' }} />
                                <span>ผลการค้นหา</span>
                            </div>
                            {displayItems.map((item, i) => (
                                <ResultRow
                                    key={item.symbol}
                                    item={item}
                                    isHighlighted={highlighted === i}
                                    onSelect={handleSelect}
                                    onMouseEnter={() => setHighlighted(i)}
                                />
                            ))}
                        </>
                    )}

                    {/* No results */}
                    {!loading && query.length > 0 && displayItems.length === 0 && (
                        <div className="py-10 text-center">
                            <div className="text-2xl mb-2">🔍</div>
                            <div className="text-xs" style={{ color: 'var(--color-text-sub)' }}>
                                ไม่พบ "<span style={{ color: 'var(--color-text)' }}>{query}</span>"
                            </div>
                            <div className="text-[10px] mt-1" style={{ color: 'var(--color-text-sub)', opacity: 0.6 }}>
                                ลองใช้ตัวย่อหุ้น เช่น PTT, AAPL, KBANK
                            </div>
                        </div>
                    )}

                    {/* Recent searches */}
                    {showRecent && (
                        <>
                            <div className="search-section-label px-5 pt-3 pb-1 flex items-center justify-between">
                                <div className="flex items-center gap-1.5">
                                    <Clock size={10} style={{ color: 'var(--color-text-sub)' }} />
                                    <span>เปิดล่าสุด</span>
                                </div>
                                <button
                                    onClick={clearRecent}
                                    className="text-[10px] transition-colors hover:underline"
                                    style={{ color: 'var(--color-text-sub)' }}
                                >
                                    ล้างทั้งหมด
                                </button>
                            </div>
                            {recent.map((item, i) => (
                                <ResultRow
                                    key={item.symbol}
                                    item={item}
                                    isHighlighted={highlighted === i}
                                    onSelect={handleSelect}
                                    onMouseEnter={() => setHighlighted(i)}
                                />
                            ))}
                        </>
                    )}

                    {/* Popular / trending */}
                    {showPopular && !showRecent && (
                        <>
                            <div className="search-section-label px-5 pt-3 pb-1 flex items-center gap-1.5">
                                <TrendingUp size={10} style={{ color: 'var(--color-green)' }} />
                                <span>ยอดนิยม</span>
                            </div>
                            {POPULAR.map((item, i) => (
                                <ResultRow
                                    key={item.symbol}
                                    item={item}
                                    isHighlighted={highlighted === i}
                                    onSelect={handleSelect}
                                    onMouseEnter={() => setHighlighted(i)}
                                />
                            ))}
                        </>
                    )}
                </div>

                {/* ── Footer hint ───────────────────────────────────────────── */}
                <div className="search-footer flex items-center gap-4 px-5 py-2.5">
                    <span className="flex items-center gap-1">
                        <kbd className="search-kbd-mini">↑</kbd>
                        <kbd className="search-kbd-mini">↓</kbd>
                        <span>เลือก</span>
                    </span>
                    <span className="flex items-center gap-1">
                        <kbd className="search-kbd-mini">↵</kbd>
                        <span>เปิด</span>
                    </span>
                    <span className="flex items-center gap-1">
                        <kbd className="search-kbd-mini">ESC</kbd>
                        <span>ปิด</span>
                    </span>
                </div>
            </div>
        </div>
    );
}
