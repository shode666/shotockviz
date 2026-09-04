/**
 * NewsPage — ข่าวและบทวิเคราะห์
 *
 * Features:
 *  - Search bar with symbol autocomplete (debounced 300ms)
 *  - Auto-loads news for the currently selected stock
 *  - Sentiment badge derived from title keywords
 *  - Works across all markets: SET, US, EU, etc.
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { Newspaper, ThumbsUp, ThumbsDown, Search, X, RefreshCw, Loader2 } from 'lucide-react';
import useAppStore from '@/store/appStore';
import stockService from '@/services/stockService';
import { timeAgo, parseSymbol, MARKET_COLORS } from '@/utils/formatters';

/* ── Helpers ────────────────────────────────────────────────────────────── */

function sentimentFromTitle(title: string): 'positive' | 'negative' | 'neutral' {
    const neg = /loss|drop|fall|decline|crash|miss|cut|warn|risk|fear|slump|plunge|disappoint|sell.?off|bear/i;
    const pos = /gain|rise|rally|surge|beat|profit|growth|record|strong|bullish|boost|soar|upbeat|outperform/i;
    if (neg.test(title)) return 'negative';
    if (pos.test(title)) return 'positive';
    return 'neutral';
}

/* ── NewsCard ───────────────────────────────────────────────────────────── */

function NewsCard({ n }: { n: any }) {
    const sentiment = n.sentiment || sentimentFromTitle(n.title);
    const sentColor = sentiment === 'positive'
        ? { bg: 'rgba(52,211,153,0.13)', text: 'var(--color-green)' }
        : sentiment === 'negative'
            ? { bg: 'rgba(248,113,113,0.13)', text: 'var(--color-red)' }
            : { bg: 'rgba(148,163,184,0.10)', text: 'var(--color-text-sub)' };

    return (
        <a
            href={n.url || '#'}
            target="_blank"
            rel="noopener noreferrer"
            className="panel border rounded-xl p-4 cursor-pointer transition-colors block"
            style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)', textDecoration: 'none', color: 'inherit' }}
            onMouseEnter={e => ((e.currentTarget as HTMLElement).style.background = 'var(--color-hover)')}
            onMouseLeave={e => ((e.currentTarget as HTMLElement).style.background = '')}
        >
            <div className="flex items-start gap-3">
                <span className="badge text-[10px] font-semibold shrink-0 mt-0.5 px-2 py-0.5 rounded-md"
                    style={{ background: sentColor.bg, color: sentColor.text }}>
                    {sentiment === 'positive' ? '▲' : sentiment === 'negative' ? '▼' : '◆'}
                </span>
                <div className="flex-1 min-w-0">
                    <div className="text-sm font-medium mb-1.5 leading-snug line-clamp-2">{n.title}</div>
                    <div className="flex items-center gap-2">
                        <span className="text-[10px] px-1.5 py-0.5 rounded"
                            style={{ background: 'var(--color-hover)', color: 'var(--color-text-sub)' }}>
                            {n.source || 'Google News'}
                        </span>
                        {n.published_at && (
                            <span className="text-[10px]" style={{ color: 'var(--color-text-sub)' }}>
                                {timeAgo(n.published_at)}
                            </span>
                        )}
                    </div>
                </div>
                {sentiment !== 'neutral' && (
                    <span className="text-[10px] font-semibold shrink-0 flex items-center gap-1"
                        style={{ color: sentColor.text }}>
                        {sentiment === 'positive'
                            ? <><ThumbsUp size={10} /> Bullish</>
                            : <><ThumbsDown size={10} /> Bearish</>}
                    </span>
                )}
            </div>
        </a>
    );
}

/* ── Main Component ─────────────────────────────────────────────────────── */

export default function NewsPage() {
    const { selectedStock } = useAppStore();

    const [searchInput, setSearchInput] = useState('');
    const [fetchSym, setFetchSym]       = useState('');
    const [news, setNews]               = useState<any[]>([]);
    const [loading, setLoading]         = useState(false);
    const searchRef = useRef<HTMLInputElement>(null);

    // ── Autocomplete ────────────────────────────────────────────────────────
    const [acResults, setAcResults]   = useState<any[]>([]);
    const [acLoading, setAcLoading]   = useState(false);
    const [showDropdown, setShowDropdown] = useState(false);
    const [acHighlight, setAcHighlight] = useState(-1);
    const acTimerRef  = useRef<ReturnType<typeof setTimeout> | null>(null);
    const dropdownRef = useRef<HTMLDivElement>(null);
    // Flag: suppress autocomplete when input is set programmatically (e.g. sidebar stock select)
    const skipAcRef   = useRef(false);

    // ── Fetch news ──────────────────────────────────────────────────────────
    const fetchNews = useCallback(async (sym: string) => {
        if (!sym) return;
        setFetchSym(sym);
        setLoading(true);
        setNews([]);
        try {
            const { data } = await stockService.getNews(sym);
            setNews((data ?? []).map((n: any) => ({
                ...n,
                sentiment: n.sentiment || sentimentFromTitle(n.title),
            })));
        } catch {
            setNews([]);
        } finally {
            setLoading(false);
        }
    }, []);

    // Auto-load when selected stock changes (e.g. user clicked a symbol in sidebar)
    useEffect(() => {
        const sym = selectedStock?.sym ?? 'NVDA';
        skipAcRef.current = true;   // don't trigger autocomplete for this programmatic update
        setSearchInput(sym);
        setShowDropdown(false);
        setAcResults([]);
        fetchNews(sym);
    }, [selectedStock?.sym]); // eslint-disable-line react-hooks/exhaustive-deps

    // ── Autocomplete: debounced search ──────────────────────────────────────
    useEffect(() => {
        // Skip autocomplete when input was set programmatically (sidebar stock select)
        if (skipAcRef.current) { skipAcRef.current = false; return; }
        const q = searchInput.trim();
        if (!q) { setAcResults([]); setShowDropdown(false); return; }
        setAcLoading(true);
        clearTimeout(acTimerRef.current ?? undefined);
        acTimerRef.current = setTimeout(async () => {
            try {
                const res = await stockService.search(q);
                const results = res.data?.results ?? res.data ?? [];
                setAcResults(results);
                setAcHighlight(-1);
                setShowDropdown(results.length > 0);
            } catch {
                setAcResults([]);
                setShowDropdown(false);
            } finally {
                setAcLoading(false);
            }
        }, 300);
        return () => clearTimeout(acTimerRef.current ?? undefined);
    }, [searchInput]);

    // Close dropdown on outside click
    useEffect(() => {
        const handler = (e: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node))
                setShowDropdown(false);
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    const handleAcSelect = (sym: string) => {
        setSearchInput(sym);
        setShowDropdown(false);
        setAcResults([]);
        setAcHighlight(-1);
        fetchNews(sym);
    };

    const handleSearch = () => {
        const s = searchInput.trim().toUpperCase();
        if (!s) return;
        setShowDropdown(false);
        fetchNews(s);
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        const visible = showDropdown && acResults.length > 0;
        if (e.key === 'ArrowDown') {
            if (!visible) return;
            e.preventDefault();
            setAcHighlight(h => (h + 1) % acResults.slice(0, 7).length);
        } else if (e.key === 'ArrowUp') {
            if (!visible) return;
            e.preventDefault();
            setAcHighlight(h => (h <= 0 ? acResults.slice(0, 7).length - 1 : h - 1));
        } else if (e.key === 'Enter') {
            if (visible && acHighlight >= 0) {
                handleAcSelect(acResults[acHighlight].symbol);
            } else {
                handleSearch();
            }
        } else if (e.key === 'Escape') {
            setShowDropdown(false);
            setAcHighlight(-1);
        }
    };

    // Sentiment counts
    const pos = news.filter(n => n.sentiment === 'positive').length;
    const neg = news.filter(n => n.sentiment === 'negative').length;
    const neu = news.filter(n => n.sentiment === 'neutral').length;

    return (
        <div className="flex-1 overflow-auto p-5" style={{ background: 'var(--color-bg)' }}>
            <div className="max-w-4xl mx-auto animate-fade-in">

                {/* ── Header ─────────────────────────────────────────────── */}
                <div className="flex items-center justify-between mb-4">
                    <h2 className="text-sm font-bold flex items-center gap-2">
                        <Newspaper size={15} style={{ color: 'var(--color-accent)' }} />
                        ข่าวและบทวิเคราะห์
                    </h2>
                    <button
                        onClick={() => fetchNews(fetchSym)}
                        disabled={loading || !fetchSym}
                        className="p-1.5 rounded-lg transition-colors hover:bg-[var(--color-hover)]"
                        style={{ color: 'var(--color-text-sub)' }}>
                        <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
                    </button>
                </div>

                {/* ── Search bar with autocomplete ────────────────────────── */}
                <div className="flex gap-2 mb-5">
                    <div className="flex-1 relative" ref={dropdownRef}>
                        <div className="flex items-center gap-2 panel border rounded-xl px-3"
                            style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                            <Search size={13} style={{ color: 'var(--color-text-sub)', flexShrink: 0 }} />
                            <input
                                ref={searchRef}
                                type="text"
                                value={searchInput}
                                onChange={e => { setSearchInput(e.target.value.toUpperCase()); setShowDropdown(true); }}
                                onKeyDown={handleKeyDown}
                                onFocus={() => acResults.length > 0 && setShowDropdown(true)}
                                placeholder="ค้นหาข่าว เช่น PTT.BK, AAPL, NVDA, ADVANC…"
                                className="flex-1 bg-transparent outline-none text-xs py-2.5"
                                style={{ color: 'var(--color-text)', caretColor: 'var(--color-accent)' }}
                            />
                            {acLoading && (
                                <Loader2 size={12} className="animate-spin shrink-0"
                                    style={{ color: 'var(--color-text-sub)' }} />
                            )}
                            {searchInput && !acLoading && (
                                <button
                                    onClick={() => { setSearchInput(''); setShowDropdown(false); setAcResults([]); }}
                                    style={{ color: 'var(--color-text-sub)', flexShrink: 0 }}>
                                    <X size={12} />
                                </button>
                            )}
                        </div>

                        {/* Autocomplete dropdown */}
                        {showDropdown && acResults.length > 0 && (
                            <div className="glass-dropdown absolute left-0 right-0 z-50 rounded-xl mt-1 overflow-hidden shadow-lg"
                                style={{ border: '1px solid var(--color-border)' }}>
                                {acResults.slice(0, 7).map((r, idx) => {
                                    const parsed = parseSymbol(r.symbol, r.market);
                                    const mktTag = r.market || parsed.market;
                                    const colors = (MARKET_COLORS as any)[mktTag] || (MARKET_COLORS as any).US;
                                    const isHighlighted = idx === acHighlight;
                                    return (
                                        <button
                                            key={r.symbol}
                                            onMouseDown={e => { e.preventDefault(); handleAcSelect(r.symbol); }}
                                            onMouseEnter={() => setAcHighlight(idx)}
                                            onMouseLeave={() => setAcHighlight(-1)}
                                            className="w-full flex items-center justify-between px-3 py-2 text-left transition-colors"
                                            style={isHighlighted ? { background: 'var(--color-hover)' } : {}}
                                        >
                                            <div className="flex-1 min-w-0">
                                                <div className="text-[11px] font-semibold"
                                                    style={{ color: 'var(--color-text)' }}>
                                                    {parsed.display}
                                                </div>
                                                <div className="text-[10px] truncate"
                                                    style={{ color: 'var(--color-text-sub)', maxWidth: 200 }}>
                                                    {r.name_th || r.name || ''}
                                                </div>
                                            </div>
                                            <span className="text-[9px] ml-2 shrink-0 px-1.5 py-0.5 rounded font-semibold"
                                                style={{ background: colors?.bg, color: colors?.text }}>
                                                {mktTag}
                                            </span>
                                        </button>
                                    );
                                })}
                            </div>
                        )}
                    </div>
                    <button
                        onClick={handleSearch}
                        disabled={loading || !searchInput.trim()}
                        className="btn-accent px-4 py-2 text-xs rounded-xl disabled:opacity-50"
                    >
                        ค้นหา
                    </button>
                </div>

                {/* ── Context + sentiment summary ──────────────────────────── */}
                {fetchSym && !loading && (
                    <div className="flex items-center gap-2 mb-3">
                        <span className="text-[10px]" style={{ color: 'var(--color-text-sub)' }}>
                            ข่าวสำหรับ:
                        </span>
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-md"
                            style={{ background: 'rgba(124,92,252,0.15)', color: 'var(--color-accent-text)' }}>
                            {fetchSym}
                        </span>
                        {news.length > 0 && (
                            <div className="flex items-center gap-1.5 ml-auto">
                                <span className="badge" style={{ background: 'var(--color-up-muted)', color: 'var(--color-up)' }}>▲ {pos}</span>
                                <span className="badge" style={{ background: 'rgba(148,163,184,0.10)', color: 'var(--color-text-sub)' }}>◆ {neu}</span>
                                <span className="badge" style={{ background: 'var(--color-down-muted)', color: 'var(--color-down)' }}>▼ {neg}</span>
                            </div>
                        )}
                    </div>
                )}

                {/* ── Loading ─────────────────────────────────────────────── */}
                {loading && (
                    <div className="flex flex-col items-center gap-3 py-16">
                        <RefreshCw size={20} className="animate-spin" style={{ color: 'var(--color-accent)' }} />
                        <p className="text-xs" style={{ color: 'var(--color-text-sub)' }}>
                            กำลังโหลดข่าว {fetchSym}…
                        </p>
                    </div>
                )}

                {/* ── Empty state ─────────────────────────────────────────── */}
                {!loading && news.length === 0 && fetchSym && (
                    <div className="text-center py-12 flex flex-col items-center gap-3">
                        <Newspaper size={28} style={{ color: 'var(--color-text-sub)' }} />
                        <p className="text-sm font-medium">ไม่พบข่าวสำหรับ {fetchSym}</p>
                        <p className="text-xs" style={{ color: 'var(--color-text-sub)' }}>
                            ลองค้นหาด้วย symbol อื่น หรือรอสักครู่แล้วลองใหม่
                        </p>
                    </div>
                )}

                {/* ── News cards ──────────────────────────────────────────── */}
                {!loading && news.length > 0 && (
                    <div className="flex flex-col gap-2.5">
                        {news.map((n, i) => <NewsCard key={i} n={n} />)}
                    </div>
                )}
            </div>
        </div>
    );
}
