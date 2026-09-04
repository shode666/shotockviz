import { useState, useEffect, useRef, useCallback } from 'react';
import { Newspaper, Briefcase, BarChart2, StickyNote, Save, Check } from 'lucide-react';
import useAppStore from '@/store/appStore';
import useAuthStore from '@/store/authStore';
import stockService from '@/services/stockService';
import portfolioService from '@/services/portfolioService';
import notesService from '@/services/notesService';
import { displaySymbol } from '@/utils/formatters';

const TABS = [
    { key: 'news', Icon: Newspaper, label: 'News' },
    { key: 'portfolio', Icon: Briefcase, label: 'Portfolio' },
    { key: 'fundamentals', Icon: BarChart2, label: 'Fundamentals' },
    { key: 'notes', Icon: StickyNote, label: 'Notes' },
];

export default function BottomPanel() {
    const { selectedStock } = useAppStore();
    const { isAuthenticated } = useAuthStore();
    const [tab, setTab] = useState('news');
    const [news, setNews] = useState([]);
    const [fundamentals, setFundamentals] = useState(null);
    const [holding, setHolding] = useState(null);
    const [loading, setLoading] = useState(false);
    // Notes state
    const [noteContent, setNoteContent] = useState('');
    const [noteSaving, setNoteSaving] = useState(false);
    const [noteSaved, setNoteSaved] = useState(false);
    const saveTimer = useRef<any>(null);

    useEffect(() => {
        if (!selectedStock?.sym) return;
        setLoading(true);

        Promise.all([
            stockService.getNews(selectedStock.sym).catch(() => ({ data: [] })),
            stockService.getFundamentals(selectedStock.sym).catch(() => ({ data: null })),
        ]).then(([newsRes, funRes]) => {
            setNews(newsRes.data || []);
            setFundamentals(funRes.data);
            setLoading(false);
        });
    }, [selectedStock?.sym]);

    // Load note when Notes tab is opened or stock changes
    useEffect(() => {
        if (tab !== 'notes' || !isAuthenticated || !selectedStock?.sym) return;
        setNoteContent('');
        notesService.get(selectedStock.sym)
            .then(r => setNoteContent(r.data?.content ?? ''))
            .catch(() => {});
    }, [tab, isAuthenticated, selectedStock?.sym]);

    const saveNote = useCallback(async () => {
        if (!isAuthenticated || !selectedStock?.sym) return;
        setNoteSaving(true);
        try {
            await notesService.upsert(selectedStock.sym, noteContent);
            setNoteSaved(true);
            setTimeout(() => setNoteSaved(false), 2000);
        } catch { /* ignore */ }
        finally { setNoteSaving(false); }
    }, [isAuthenticated, selectedStock?.sym, noteContent]);

    // Auto-save after 1.5s of no typing
    const handleNoteChange = (v: string) => {
        setNoteContent(v);
        setNoteSaved(false);
        clearTimeout(saveTimer.current);
        saveTimer.current = setTimeout(saveNote, 1500);
    };

    // Fetch portfolio holding for selected stock when portfolio tab is open
    useEffect(() => {
        if (tab !== 'portfolio' || !isAuthenticated || !selectedStock?.sym) {
            setHolding(null);
            return;
        }
        portfolioService.getAnalytics()
            .then(res => {
                const h = (res.data?.holdings ?? []).find(
                    (h: any) => h.symbol === selectedStock.sym
                );
                setHolding(h ?? null);
            })
            .catch(() => setHolding(null));
    }, [tab, isAuthenticated, selectedStock?.sym]);

    const funData = [
        ['P/E', fundamentals?.pe_ratio?.toFixed(2) ?? '—'],
        ['Div Yield', fundamentals?.dividend_yield ? (fundamentals.dividend_yield * 100).toFixed(2) + '%' : '—'],
        ['Mkt Cap', fundamentals?.market_cap ? (fundamentals.market_cap / 1e9).toFixed(2) + 'B' : '—'],
        ['Beta', fundamentals?.beta?.toFixed(2) ?? '—'],
    ];

    return (
        <div className="panel border-t flex flex-col" style={{ height: 200, borderTopWidth: 1, borderTopStyle: 'solid', borderColor: 'var(--color-border)' }}>
            {/* Tab headers */}
            <div className="flex border-b" style={{ borderColor: 'var(--color-border)' }}>
                {TABS.map(({ key, Icon, label }) => (
                    <button
                        key={key}
                        onClick={() => setTab(key)}
                        className="flex items-center gap-1.5 text-[11px] px-4 py-2 font-medium transition-all"
                        style={{
                            color: tab === key ? 'var(--color-accent)' : 'var(--color-text-sub)',
                            borderBottom: tab === key ? '2px solid var(--color-accent)' : '2px solid transparent',
                        }}
                    >
                        <Icon size={12} />
                        {label}
                    </button>
                ))}
            </div>

            {/* Tab content */}
            <div className="flex-1 overflow-y-auto p-3">
                {loading ? (
                    <div className="text-[11px] text-center mt-4" style={{ color: 'var(--color-text-sub)' }}>กำลังโหลด...</div>
                ) : (
                    <>
                        {tab === 'news' && (
                            <div className="flex flex-col gap-1.5">
                                {news.length === 0 ? (
                                    <div className="text-[11px] text-center mt-4" style={{ color: 'var(--color-text-sub)' }}>ไม่มีข่าวล่าสุด</div>
                                ) : (
                                    news.slice(0, 5).map((n, i) => (
                                        <a
                                            key={i}
                                            href={n.url}
                                            target="_blank"
                                            rel="noreferrer"
                                            className="flex items-start gap-2 p-2 rounded-lg transition-colors"
                                            onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-hover)')}
                                            onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                                        >
                                            <span className="badge badge-violet flex-shrink-0 text-[10px]">{n.source}</span>
                                            <span className="text-[11px] flex-1 font-medium hover:underline">{n.title}</span>
                                            <span className="text-[10px] flex-shrink-0" style={{ color: 'var(--color-text-sub)' }}>
                                                {new Date(n.published_at).toLocaleDateString('th-TH', { month: 'short', day: 'numeric' })}
                                            </span>
                                        </a>
                                    ))
                                )}
                            </div>
                        )}

                        {tab === 'portfolio' && (
                            <div className="h-full flex flex-col justify-center">
                                {!isAuthenticated ? (
                                    <div className="text-[11px] text-center" style={{ color: 'var(--color-text-sub)' }}>
                                        เข้าสู่ระบบเพื่อดูพอร์ตการลงทุน
                                    </div>
                                ) : holding ? (
                                    <div className="grid grid-cols-4 gap-3">
                                        {[
                                            ['จำนวน', holding.qty?.toLocaleString() ?? '—'],
                                            ['ต้นทุนเฉลี่ย', holding.avg_cost?.toFixed(2) ?? '—'],
                                            ['มูลค่าปัจจุบัน', holding.current_value?.toFixed(2) ?? '—'],
                                            ['กำไร/ขาดทุน%', holding.unrealized_pl_pct != null
                                                ? `${holding.unrealized_pl_pct >= 0 ? '+' : ''}${holding.unrealized_pl_pct.toFixed(2)}%`
                                                : '—'],
                                        ].map(([label, val], i) => (
                                            <div key={i} className="rounded-xl p-3 border" style={{ background: 'var(--color-input-bg)', borderColor: 'var(--color-border)' }}>
                                                <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: 'var(--color-text-sub)' }}>{label}</div>
                                                <div className="text-sm font-bold tabular-nums"
                                                    style={{ color: i === 3 && holding.unrealized_pl_pct != null
                                                        ? (holding.unrealized_pl_pct >= 0 ? 'var(--color-green)' : 'var(--color-red)')
                                                        : undefined }}>
                                                    {val}
                                                </div>
                                            </div>
                                        ))}
                                    </div>
                                ) : (
                                    <div className="text-[11px] text-center" style={{ color: 'var(--color-text-sub)' }}>
                                        ไม่มีหุ้น {displaySymbol(selectedStock?.sym)} ในพอร์ต
                                    </div>
                                )}
                            </div>
                        )}

                        {tab === 'notes' && (
                            <div className="h-full flex flex-col gap-2">
                                {!isAuthenticated ? (
                                    <div className="text-[11px] text-center mt-4" style={{ color: 'var(--color-text-sub)' }}>
                                        Login เพื่อบันทึก investment thesis
                                    </div>
                                ) : (
                                    <>
                                        <div className="flex items-center justify-between">
                                            <span className="text-[10px]" style={{ color: 'var(--color-text-sub)' }}>
                                                บันทึก thesis สำหรับ {displaySymbol(selectedStock?.sym)}
                                            </span>
                                            <div className="flex items-center gap-1.5">
                                                {noteSaved && (
                                                    <span className="text-[10px] flex items-center gap-0.5" style={{ color: 'var(--color-green)' }}>
                                                        <Check size={11} strokeWidth={2} aria-hidden="true" /> บันทึกแล้ว
                                                    </span>
                                                )}
                                                <button onClick={saveNote} disabled={noteSaving}
                                                    className="flex items-center gap-1 text-[10px] px-2 py-1 rounded-lg transition-colors"
                                                    style={{ background: 'var(--color-accent-glow, rgba(124,92,252,0.15))', color: 'var(--color-accent)' }}>
                                                    <Save size={9} /> {noteSaving ? 'กำลังบันทึก...' : 'บันทึก'}
                                                </button>
                                            </div>
                                        </div>
                                        <textarea
                                            className="flex-1 w-full resize-none text-[11px] rounded-lg p-2 outline-none"
                                            style={{
                                                background: 'var(--color-input-bg)',
                                                border: '1px solid var(--color-border)',
                                                color: 'var(--color-text)',
                                            }}
                                            placeholder={`เหตุผลที่ซื้อ ${displaySymbol(selectedStock?.sym)}, จุดเข้า, เป้าหมายราคา, ความเสี่ยง...`}
                                            value={noteContent}
                                            onChange={e => handleNoteChange(e.target.value)}
                                        />
                                    </>
                                )}
                            </div>
                        )}

                        {tab === 'fundamentals' && (
                            <div className="grid grid-cols-4 gap-3">
                                {funData.map(([k, v]) => (
                                    <div key={k} className="rounded-xl p-3 border" style={{ background: 'var(--color-input-bg)', borderColor: 'var(--color-border)' }}>
                                        <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: 'var(--color-text-sub)' }}>{k}</div>
                                        <div className="text-sm font-bold">{v}</div>
                                    </div>
                                ))}
                            </div>
                        )}
                    </>
                )}
            </div>
        </div>
    );
}
