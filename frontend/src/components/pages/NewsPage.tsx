import { useState, useEffect } from 'react';
import { Newspaper, ThumbsUp, ThumbsDown } from 'lucide-react';
import useAppStore from '@/store/appStore';
import stockService from '@/services/stockService';

const TAGS = ['ทั้งหมด', 'SET', 'US', 'Watchlist'];

interface NewsItem {
    title: string;
    url: string;
    source: string;
    published_at: string;
    summary?: string;
    sentiment?: 'positive' | 'negative' | 'neutral';
}

function sentimentFromTitle(title: string): 'positive' | 'negative' | 'neutral' {
    const neg = /loss|drop|fall|decline|crash|miss|cut|warn|risk|fear|slump|plunge|disappoint/i;
    const pos = /gain|rise|rally|surge|beat|profit|growth|record|strong|bullish|boost|soar/i;
    if (neg.test(title)) return 'negative';
    if (pos.test(title)) return 'positive';
    return 'neutral';
}

function timeAgo(dateStr: string): string {
    const diff = Date.now() - new Date(dateStr).getTime();
    const mins = Math.floor(diff / 60000);
    if (mins < 60) return `${mins} นาทีที่แล้ว`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs} ชม.ที่แล้ว`;
    return `${Math.floor(hrs / 24)} วันที่แล้ว`;
}

export default function NewsPage() {
    const { selectedStock } = useAppStore();
    const [news, setNews] = useState<NewsItem[]>([]);
    const [loading, setLoading] = useState(false);
    const [activeTag, setActiveTag] = useState('ทั้งหมด');

    useEffect(() => {
        const sym = selectedStock?.sym || 'PTT.BK';
        setLoading(true);
        stockService.getNews(sym)
            .then(({ data }: { data: NewsItem[] }) => {
                const enriched = data.map((n: NewsItem) => ({
                    ...n,
                    sentiment: n.sentiment || sentimentFromTitle(n.title),
                }));
                setNews(enriched);
            })
            .catch(() => setNews([]))
            .finally(() => setLoading(false));
    }, [selectedStock?.sym]);

    const selectedMarket = selectedStock?.sym?.endsWith('.BK') ? 'SET' : 'US';
    const displayed =
        activeTag === 'ทั้งหมด' || activeTag === 'Watchlist'
            ? news
            : activeTag === selectedMarket
                ? news
                : [];

    return (
        <div className="flex-1 overflow-auto p-6">
            <div className="max-w-4xl mx-auto animate-fade-in">
                <div className="flex items-center gap-2 mb-4">
                    <h2 className="text-lg font-bold flex items-center gap-2"><Newspaper size={18} /> ข่าวและบทวิเคราะห์</h2>
                    {selectedStock?.sym && (
                        <span
                            className="badge text-xs"
                            style={{ background: 'rgba(124,92,252,0.15)', color: 'var(--color-accent)' }}
                        >
                            {selectedStock.sym}
                        </span>
                    )}
                </div>

                {/* Tag filters */}
                <div className="flex gap-2 mb-4">
                    {TAGS.map((tag) => (
                        <button
                            key={tag}
                            onClick={() => setActiveTag(tag)}
                            className="btn-outline text-xs"
                            style={activeTag === tag ? {
                                background: 'var(--color-accent)',
                                color: '#fff',
                                borderColor: 'var(--color-accent)',
                            } : {}}
                        >
                            {tag}
                        </button>
                    ))}
                </div>

                {/* Loading */}
                {loading && (
                    <div className="text-center py-16 text-sm" style={{ color: 'var(--color-text-sub)' }}>
                        กำลังโหลดข่าว...
                    </div>
                )}

                {/* Empty */}
                {!loading && displayed.length === 0 && (
                    <div className="text-center py-16 text-sm" style={{ color: 'var(--color-text-sub)' }}>
                        {activeTag !== 'ทั้งหมด' && activeTag !== 'Watchlist' && activeTag !== selectedMarket
                            ? `ไม่มีข่าว ${activeTag} สำหรับ ${selectedStock?.sym || 'หุ้นนี้'}`
                            : `ไม่พบข่าวสำหรับ ${selectedStock?.sym || 'หุ้นที่เลือก'}`}
                    </div>
                )}

                {/* News cards */}
                {!loading && (
                    <div className="flex flex-col gap-3">
                        {displayed.map((n, i) => (
                            <a
                                key={i}
                                href={n.url || '#'}
                                target="_blank"
                                rel="noopener noreferrer"
                                className="panel border rounded-2xl p-4 cursor-pointer transition-all block"
                                style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)', textDecoration: 'none', color: 'inherit' }}
                                onMouseEnter={(e) => ((e.currentTarget as HTMLElement).style.background = 'var(--color-hover)')}
                                onMouseLeave={(e) => ((e.currentTarget as HTMLElement).style.background = 'var(--color-panel)')}
                            >
                                <div className="flex items-start gap-3">
                                    <span
                                        className="badge text-xs flex-shrink-0 mt-0.5"
                                        style={{
                                            background: n.sentiment === 'positive'
                                                ? 'rgba(52,211,153,0.15)'
                                                : n.sentiment === 'negative'
                                                    ? 'rgba(248,113,113,0.15)'
                                                    : 'rgba(148,163,184,0.15)',
                                            color: n.sentiment === 'positive'
                                                ? 'var(--color-green)'
                                                : n.sentiment === 'negative'
                                                    ? 'var(--color-red)'
                                                    : 'var(--color-text-sub)',
                                        }}
                                    >
                                        {n.source || selectedStock?.sym || 'NEWS'}
                                    </span>
                                    <div className="flex-1 min-w-0">
                                        <div className="text-sm font-medium mb-1 leading-snug">{n.title}</div>
                                        <div className="text-xs" style={{ color: 'var(--color-text-sub)' }}>
                                            {n.published_at ? timeAgo(n.published_at) : ''}
                                        </div>
                                    </div>
                                    {n.sentiment && n.sentiment !== 'neutral' && (
                                        <div
                                            className="badge text-xs flex-shrink-0"
                                            style={{
                                                background: n.sentiment === 'positive'
                                                    ? 'rgba(52,211,153,0.1)'
                                                    : 'rgba(248,113,113,0.1)',
                                                color: n.sentiment === 'positive'
                                                    ? 'var(--color-green)'
                                                    : 'var(--color-red)',
                                            }}
                                        >
                                            {n.sentiment === 'positive'
                                                ? <span className="flex items-center gap-1"><ThumbsUp size={11} /> Positive</span>
                                                : <span className="flex items-center gap-1"><ThumbsDown size={11} /> Negative</span>}
                                        </div>
                                    )}
                                </div>
                            </a>
                        ))}
                    </div>
                )}
            </div>
        </div>
    );
}
