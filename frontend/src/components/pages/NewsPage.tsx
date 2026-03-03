/**
 * NewsPage — ข่าวและบทวิเคราะห์
 *
 * Features:
 *  - Search bar to look up news for any symbol
 *  - Tabs: ทั้งหมด (current), SET (PTT.BK), US (AAPL/NVDA), Watchlist
 *  - Sentiment badge derived from title keywords
 *  - Symbol is validated before being used as API param
 */
import { useState, useEffect, useCallback, useRef } from 'react';
import { Newspaper, ThumbsUp, ThumbsDown, Search, X, RefreshCw } from 'lucide-react';
import useAppStore from '@/store/appStore';
import useAuthStore from '@/store/authStore';
import stockService from '@/services/stockService';
import watchlistService from '@/services/watchlistService';
import { timeAgo } from '@/utils/formatters';

/* ── Constants ─────────────────────────────────────────────────────────── */

const TABS = ['ทุกข่าว', 'หุ้น SET', 'หุ้น US', 'Watchlist'] as const;
type Tab = (typeof TABS)[number];

// Default symbol per tab when no context is available
const TAB_DEFAULT_SYM: Record<Tab, string> = {
    'ทุกข่าว': 'NVDA',
    'หุ้น SET': 'PTT.BK',
    'หุ้น US': 'AAPL',
    'Watchlist': 'NVDA',
};

// Regex to validate a reasonable stock symbol (no arbitrary garbage)
const VALID_SYM = /^[\^]?[A-Z0-9]{1,10}(\.[A-Z]{1,4}|=[A-Z]|=F)?$/;

function sanitizeSym(raw: string | undefined | null): string | null {
    if (!raw) return null;
    const s = raw.trim().toUpperCase();
    return VALID_SYM.test(s) ? s : null;
}

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
                        <span className="text-[10px] px-1.5 py-0.5 rounded" style={{ background: 'var(--color-hover)', color: 'var(--color-text-sub)' }}>
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
                    <span className="text-[10px] font-semibold shrink-0 flex items-center gap-1" style={{ color: sentColor.text }}>
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
    const { isAuthenticated } = useAuthStore();

    const [activeTab, setActiveTab] = useState<Tab>('ทุกข่าว');
    const [searchInput, setSearchInput] = useState('');
    const [fetchSym, setFetchSym] = useState<string>('');     // the symbol actually used to fetch
    const [news, setNews] = useState<any[]>([]);
    const [loading, setLoading] = useState(false);
    const [watchlistSyms, setWatchlistSyms] = useState<string[]>([]);
    const searchRef = useRef<HTMLInputElement>(null);

    // Load user watchlist symbols once (same format as Sidebar)
    useEffect(() => {
        if (!isAuthenticated) return;
        watchlistService.getAll()
            .then((r: any) => {
                const lists = r.data ?? [];
                const first = lists[0];
                const syms = (first?.items ?? []).map((i: any) => i.symbol).filter(Boolean);
                setWatchlistSyms(syms);
            })
            .catch(() => {});
    }, [isAuthenticated]);

    // Determine symbol to fetch based on active tab + selectedStock
    const resolveSymbol = useCallback((tab: Tab): string => {
        if (tab === 'ทุกข่าว') {
            return sanitizeSym(selectedStock?.sym) ?? TAB_DEFAULT_SYM[tab];
        }
        if (tab === 'หุ้น SET') {
            // prefer selected if it's a Thai stock
            if (selectedStock?.sym?.toUpperCase().endsWith('.BK')) {
                return sanitizeSym(selectedStock.sym) ?? TAB_DEFAULT_SYM[tab];
            }
            return TAB_DEFAULT_SYM[tab];
        }
        if (tab === 'หุ้น US') {
            const s = sanitizeSym(selectedStock?.sym);
            if (s && !s.endsWith('.BK') && !s.startsWith('^')) return s;
            return TAB_DEFAULT_SYM[tab];
        }
        if (tab === 'Watchlist') {
            return watchlistSyms[0] ?? sanitizeSym(selectedStock?.sym) ?? TAB_DEFAULT_SYM[tab];
        }
        return TAB_DEFAULT_SYM[tab];
    }, [selectedStock, watchlistSyms]);

    const fetchNews = useCallback(async (sym: string) => {
        if (!sym) return;
        setFetchSym(sym);
        setLoading(true);
        setNews([]);
        try {
            const { data } = await stockService.getNews(sym);
            const enriched = (data ?? []).map((n: any) => ({
                ...n,
                sentiment: n.sentiment || sentimentFromTitle(n.title),
            }));
            setNews(enriched);
        } catch {
            setNews([]);
        } finally {
            setLoading(false);
        }
    }, []);

    // When tab changes → resolve symbol and fetch
    useEffect(() => {
        const sym = resolveSymbol(activeTab);
        setSearchInput(sym);
        fetchNews(sym);
    }, [activeTab, resolveSymbol]); // eslint-disable-line react-hooks/exhaustive-deps

    // Handle manual search submit
    const handleSearch = () => {
        const s = searchInput.trim().toUpperCase();
        if (!s) return;
        fetchNews(s);
    };

    const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
        if (e.key === 'Enter') handleSearch();
    };

    // Sentiment breakdown counts
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
                    <button onClick={() => fetchNews(fetchSym || resolveSymbol(activeTab))}
                        disabled={loading}
                        className="p-1.5 rounded-lg transition-colors hover:bg-[var(--color-hover)]"
                        style={{ color: 'var(--color-text-sub)' }}>
                        <RefreshCw size={13} className={loading ? 'animate-spin' : ''} />
                    </button>
                </div>

                {/* ── Search bar ──────────────────────────────────────────── */}
                <div className="flex gap-2 mb-4">
                    <div className="flex-1 flex items-center gap-2 panel border rounded-xl px-3"
                        style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                        <Search size={13} style={{ color: 'var(--color-text-sub)', flexShrink: 0 }} />
                        <input
                            ref={searchRef}
                            type="text"
                            value={searchInput}
                            onChange={e => setSearchInput(e.target.value.toUpperCase())}
                            onKeyDown={handleKeyDown}
                            placeholder="ค้นหาข่าว เช่น PTT.BK, AAPL, NVDA…"
                            className="flex-1 bg-transparent outline-none text-xs py-2.5"
                            style={{ color: 'var(--color-text)', caretColor: 'var(--color-accent)' }}
                        />
                        {searchInput && (
                            <button onClick={() => setSearchInput('')}
                                style={{ color: 'var(--color-text-sub)', flexShrink: 0 }}>
                                <X size={12} />
                            </button>
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

                {/* ── Tab bar ─────────────────────────────────────────────── */}
                <div className="flex gap-1 mb-4 border-b" style={{ borderColor: 'var(--color-border)' }}>
                    {TABS.map((tab) => (
                        <button
                            key={tab}
                            onClick={() => setActiveTab(tab)}
                            className="px-4 py-2 text-xs font-semibold relative transition-colors"
                            style={{ color: activeTab === tab ? 'var(--color-accent)' : 'var(--color-text-sub)' }}
                        >
                            {tab}
                            {activeTab === tab && (
                                <span className="absolute bottom-0 left-0 right-0 h-0.5 rounded-t-full"
                                    style={{ background: 'var(--color-accent)' }} />
                            )}
                        </button>
                    ))}
                </div>

                {/* ── Fetch context badge ─────────────────────────────────── */}
                {fetchSym && !loading && (
                    <div className="flex items-center gap-2 mb-3">
                        <span className="text-[10px]" style={{ color: 'var(--color-text-sub)' }}>กำลังดูข่าวสำหรับ:</span>
                        <span className="text-[10px] font-bold px-2 py-0.5 rounded-md"
                            style={{ background: 'rgba(124,92,252,0.15)', color: 'var(--color-accent)' }}>
                            {fetchSym}
                        </span>
                        {news.length > 0 && (
                            <div className="flex items-center gap-1.5 ml-auto">
                                <span className="text-[10px] font-semibold" style={{ color: 'var(--color-green)' }}>▲ {pos}</span>
                                <span className="text-[10px] font-semibold" style={{ color: 'var(--color-red)' }}>▼ {neg}</span>
                                <span className="text-[10px] font-semibold" style={{ color: 'var(--color-text-sub)' }}>◆ {neu}</span>
                            </div>
                        )}
                    </div>
                )}

                {/* ── Loading ─────────────────────────────────────────────── */}
                {loading && (
                    <div className="flex flex-col items-center gap-3 py-16">
                        <RefreshCw size={20} className="animate-spin" style={{ color: 'var(--color-accent)' }} />
                        <p className="text-xs" style={{ color: 'var(--color-text-sub)' }}>กำลังโหลดข่าว {fetchSym}…</p>
                    </div>
                )}

                {/* ── Empty state ─────────────────────────────────────────── */}
                {!loading && news.length === 0 && (
                    <div className="text-center py-12 flex flex-col items-center gap-3">
                        <Newspaper size={28} style={{ color: 'var(--color-text-sub)' }} />
                        <p className="text-sm font-medium">ไม่พบข่าวสำหรับ {fetchSym}</p>
                        <p className="text-xs" style={{ color: 'var(--color-text-sub)' }}>
                            ลองค้นหาด้วย symbol ที่แตกต่าง หรือตรวจสอบการเชื่อมต่ออินเทอร์เน็ต
                        </p>
                        <button onClick={() => { setSearchInput('NVDA'); fetchNews('NVDA'); }}
                            className="btn-outline text-xs mt-1">
                            ลองดูข่าว NVDA
                        </button>
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
