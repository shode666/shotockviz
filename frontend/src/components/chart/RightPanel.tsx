import { useState, useEffect, useRef, useCallback } from 'react';
import { BellPlus, Timer, Newspaper, Briefcase, BarChart2, StickyNote, Save, Check, X, Info } from 'lucide-react';
import useAppStore from '@/store/appStore';
import useAuthStore from '@/store/authStore';
import stockService from '@/services/stockService';
import portfolioService from '@/services/portfolioService';
import notesService from '@/services/notesService';
import alertService from '@/services/alertService';
import { calculateRSI } from '@/utils/indicators';
import { displaySymbol } from '@/utils/formatters';
import toast from 'react-hot-toast';

function isTimeoutError(err: any): boolean {
    return err?.code === 'ECONNABORTED' || !!err?.message?.includes('timeout');
}

const TABS = [
    { key: 'info', Icon: Info, label: 'Info' },
    { key: 'news', Icon: Newspaper, label: 'News' },
    { key: 'portfolio', Icon: Briefcase, label: 'Portfolio' },
    { key: 'fundamentals', Icon: BarChart2, label: 'Fundamentals' },
    { key: 'notes', Icon: StickyNote, label: 'Notes' },
];

interface RightPanelProps {
    selectedStock: any;
    isOpen: boolean;
    onClose: () => void;
}

export default function RightPanel({ selectedStock, isOpen, onClose }: RightPanelProps) {
    const { isAuthenticated } = useAuthStore();
    const [tab, setTab] = useState('info');

    // Info tab state (Quick Alert + Stats + RSI Gauge)
    const [fundamentals, setFundamentals] = useState(null);
    const [quote, setQuote] = useState(null);
    const [rsi, setRsi] = useState<number | null>(null);
    const [timedOut, setTimedOut] = useState(false);

    // News/Fundamentals tab state (moved from BottomPanel)
    const [news, setNews] = useState([]);
    const [holding, setHolding] = useState(null);
    const [contentLoading, setContentLoading] = useState(false);

    // Notes tab state (moved from BottomPanel)
    const [noteContent, setNoteContent] = useState('');
    const [noteSaving, setNoteSaving] = useState(false);
    const [noteSaved, setNoteSaved] = useState(false);
    const saveTimer = useRef<any>(null);

    const fetchQuote = useCallback((sym: string, signal: AbortSignal) => {
        stockService.getQuote(sym)
            .then(res => {
                if (signal.aborted) return;
                if (res.data?.price != null) setQuote(res.data);
            })
            .catch((err) => {
                if (signal.aborted) return;
                if (isTimeoutError(err)) setTimedOut(true);
            });
    }, []);

    const fetchAll = useCallback((sym: string, signal: AbortSignal) => {
        setTimedOut(false);

        stockService.getFundamentals(sym)
            .then(res => { if (!signal.aborted) setFundamentals(res.data); })
            .catch((err) => {
                if (signal.aborted) return;
                if (isTimeoutError(err)) setTimedOut(true);
                setFundamentals(null);
            });

        fetchQuote(sym, signal);

        stockService.getHistory(sym, '1D')
            .then(res => {
                if (signal.aborted) return;
                const barsData = res.data.bars ?? [];
                if (barsData.length >= 14) {
                    const rsiData = calculateRSI(barsData, 14);
                    const last = rsiData.at(-1);
                    setRsi(last?.value ?? null);
                }
            })
            .catch((err) => {
                if (signal.aborted) return;
                if (isTimeoutError(err)) setTimedOut(true);
                setRsi(null);
            });
    }, []);

    useEffect(() => {
        if (!selectedStock?.sym) return;
        setFundamentals(null);
        setQuote(null);
        setRsi(null);
        setTimedOut(false);

        const controller = new AbortController();
        fetchAll(selectedStock.sym, controller.signal);

        return () => {
            controller.abort();
        };
    }, [selectedStock?.sym, fetchAll]);

    // Escape closes the panel — bd:ux-2026-09 Chris review (Q-UX2): established
    // pattern already used by SearchModal.tsx:163. `onClose` (passed down from
    // ChartPage) also returns focus to the toggle button, so Escape/backdrop/X
    // all converge on the same close+focus-return behavior.
    useEffect(() => {
        if (!isOpen) return;
        const handler = (e: KeyboardEvent) => {
            if (e.key === 'Escape') onClose();
        };
        window.addEventListener('keydown', handler);
        return () => window.removeEventListener('keydown', handler);
    }, [isOpen, onClose]);

    // News + fundamentals summary (loaded once per symbol, regardless of active tab)
    useEffect(() => {
        if (!selectedStock?.sym) return;
        setContentLoading(true);
        stockService.getNews(selectedStock.sym).catch(() => ({ data: [] })).then((newsRes: any) => {
            setNews(newsRes.data || []);
            setContentLoading(false);
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

    const stats = [
        ['52W High', fundamentals?.week_52_high?.toFixed(2) ?? '—'],
        ['52W Low', fundamentals?.week_52_low?.toFixed(2) ?? '—'],
        ['Avg Vol', fundamentals?.avg_volume ? (fundamentals.avg_volume / 1000000).toFixed(1) + 'M' : '—'],
        ['Beta', fundamentals?.beta?.toFixed(2) ?? '—'],
        ['EPS', fundamentals?.eps?.toFixed(2) ?? '—'],
    ];

    const funData = [
        ['P/E', fundamentals?.pe_ratio?.toFixed(2) ?? '—'],
        ['Div Yield', fundamentals?.dividend_yield ? (fundamentals.dividend_yield * 100).toFixed(2) + '%' : '—'],
        ['Mkt Cap', fundamentals?.market_cap ? (fundamentals.market_cap / 1e9).toFixed(2) + 'B' : '—'],
        ['Beta', fundamentals?.beta?.toFixed(2) ?? '—'],
    ];

    const targetPrice = quote?.price ? parseFloat((quote.price * 1.05).toFixed(2)) : null;

    const handleQuickAlert = async () => {
        if (!selectedStock?.sym || targetPrice === null) return;
        try {
            await alertService.create({
                symbol: selectedStock.sym,
                alert_type: 'PRICE_ABOVE',
                condition: 'GREATER_THAN',
                value: targetPrice,
                channel: 'IN_APP'
            });
            toast.success(`Alert set for ${selectedStock.sym} at ${targetPrice}`);
        } catch {
            toast.error('Failed to set alert');
        }
    };

    const rsiPct = rsi != null ? Math.min(Math.max(rsi, 0), 100) : null;
    const rsiColor = rsi == null ? 'var(--color-text-sub)'
        : rsi < 30 ? 'var(--color-green)'
        : rsi > 70 ? 'var(--color-red)'
        : 'var(--color-yellow)';

    return (
        <>
            {/* Backdrop — mobile bottom-sheet only (Uma #5: panel must not dock permanently on small screens) */}
            {isOpen && (
                <div
                    className="fixed inset-0 z-20 md:hidden"
                    style={{ background: 'rgba(0,0,0,0.45)' }}
                    onClick={onClose}
                    aria-hidden="true"
                />
            )}
            <aside
                className={`panel fixed z-30 flex flex-col overflow-hidden transition-transform duration-200
                    inset-x-0 bottom-0 max-h-[70vh] rounded-t-2xl border-t
                    md:top-12 md:bottom-0 md:right-0 md:left-auto md:inset-x-auto md:w-[260px] md:max-h-none md:rounded-none md:border-l md:border-t-0
                    ${isOpen ? 'translate-y-0 md:translate-x-0' : 'translate-y-full md:translate-y-0 md:translate-x-full'}`}
                style={{ borderColor: 'var(--color-border)' }}
                aria-label="รายละเอียดหุ้น"
                // bd:ux-2026-09 g2 (Uma #1) — `inert` (not aria-hidden) while
                // closed: aria-hidden with focusable descendants (buttons,
                // textarea, links) is an axe `aria-hidden-focus` violation.
                // `inert` removes the whole subtree from focus + the a11y tree,
                // and React 19 renders it as a native boolean attribute.
                inert={!isOpen}
            >
                {/* Panel header */}
                <div className="flex items-center justify-between px-3 py-2 border-b shrink-0" style={{ borderColor: 'var(--color-border)' }}>
                    <span className="text-xs font-bold">{displaySymbol(selectedStock?.sym)}</span>
                    <button onClick={onClose} className="p-1 rounded-lg transition-colors hover:bg-[var(--color-hover)]" aria-label="ปิดแผงข้อมูล">
                        <X size={14} strokeWidth={2} aria-hidden="true" />
                    </button>
                </div>

                {/* Tab headers */}
                <div className="flex border-b overflow-x-auto shrink-0" style={{ borderColor: 'var(--color-border)' }}>
                    {TABS.map(({ key, Icon, label }) => (
                        <button
                            key={key}
                            onClick={() => setTab(key)}
                            className="flex items-center gap-1 text-[10px] px-2.5 py-2 font-medium transition-all whitespace-nowrap"
                            style={{
                                color: tab === key ? 'var(--color-accent)' : 'var(--color-text-sub)',
                                borderBottom: tab === key ? '2px solid var(--color-accent)' : '2px solid transparent',
                            }}
                        >
                            <Icon size={11} />
                            {label}
                        </button>
                    ))}
                </div>

                {/* Tab content */}
                <div className="flex-1 overflow-y-auto">
                    {tab === 'info' && (
                        <>
                            {/* Quick Alert */}
                            <div className="p-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
                                <div className="text-[10px] uppercase tracking-wider mb-2 font-semibold" style={{ color: 'var(--color-text-sub)' }}>Quick Alert</div>
                                <div className="flex items-center justify-between p-2 rounded-xl mb-2" style={{ background: 'var(--color-input-bg)' }}>
                                    <span className="text-[11px]" style={{ color: 'var(--color-text-sub)' }}>Target (+5%)</span>
                                    <span className="text-[11px] font-medium">{targetPrice ?? '—'}</span>
                                </div>
                                <button
                                    onClick={handleQuickAlert}
                                    disabled={targetPrice === null}
                                    className="btn-accent w-full py-1.5 text-[11px] font-medium rounded-lg disabled:opacity-40 flex items-center justify-center gap-1.5"
                                >
                                    <BellPlus size={12} />
                                    Set Alert
                                </button>
                            </div>

                            {/* Stats */}
                            <div className="p-3 border-b" style={{ borderColor: 'var(--color-border)' }}>
                                <div className="text-[10px] uppercase tracking-wider mb-2 font-semibold" style={{ color: 'var(--color-text-sub)' }}>Stats</div>
                                {timedOut && (
                                    <div className="text-[11px] py-1 mb-1 flex items-center gap-1" style={{ color: 'var(--color-text-sub)' }}>
                                        <Timer size={12} strokeWidth={2} aria-hidden="true" /> Timed out —{' '}
                                        <button
                                            className="underline"
                                            style={{ color: 'var(--color-accent)', background: 'none', border: 'none', cursor: 'pointer', padding: 0 }}
                                            onClick={() => {
                                                if (!selectedStock?.sym) return;
                                                setTimedOut(false);
                                                setFundamentals(null);
                                                setQuote(null);
                                                setRsi(null);
                                                const ctrl = new AbortController();
                                                fetchAll(selectedStock.sym, ctrl.signal);
                                            }}
                                        >retry?</button>
                                    </div>
                                )}
                                {stats.map(([k, v]) => (
                                    <div key={k} className="flex justify-between items-center py-1.5 border-b last:border-0" style={{ borderColor: 'color-mix(in srgb, var(--color-border) 40%, transparent)' }}>
                                        <span className="text-[11px]" style={{ color: 'var(--color-text-sub)' }}>{k}</span>
                                        <span className="text-[11px] font-medium tabular-nums">{v}</span>
                                    </div>
                                ))}
                            </div>

                            {/* RSI Gauge */}
                            <div className="p-3">
                                <div className="text-[10px] uppercase tracking-wider mb-2 font-semibold" style={{ color: 'var(--color-text-sub)' }}>RSI (14)</div>
                                {rsiPct != null ? (
                                    <>
                                        <div className="relative my-3">
                                            {/* bd:ux-2026-09 Chris review — hardcoded #f87171 matched
                                                neither theme's --color-red (#ef4444 light / #f43f5e
                                                dark, styles.css:43,112); tokens track theme instead. */}
                                            <div className="h-1.5 rounded-full overflow-hidden" style={{ background: 'linear-gradient(to right, var(--color-green), var(--color-yellow), var(--color-red))' }}>
                                                <div
                                                    className="absolute top-1/2 -translate-y-1/2 w-3 h-3 rounded-full bg-white border-2 shadow"
                                                    style={{ left: `${rsiPct}%`, borderColor: 'var(--color-accent)', transform: 'translate(-50%, -50%)' }}
                                                />
                                            </div>
                                        </div>
                                        <div className="flex justify-between items-center mt-2">
                                            <span className="text-[10px] font-medium" style={{ color: 'var(--color-green)' }}>Oversold</span>
                                            <span className="text-xs font-bold" style={{ color: rsiColor }}>{rsiPct.toFixed(1)}</span>
                                            <span className="text-[10px] font-medium" style={{ color: 'var(--color-red)' }}>Overbought</span>
                                        </div>
                                    </>
                                ) : (
                                    <div className="text-[11px] py-4 text-center" style={{ color: 'var(--color-text-sub)' }}>—</div>
                                )}
                            </div>
                        </>
                    )}

                    {tab !== 'info' && (
                        <div className="p-3">
                            {contentLoading && tab === 'news' ? (
                                <div className="text-[11px] text-center mt-4" style={{ color: 'var(--color-text-sub)' }}>กำลังโหลด...</div>
                            ) : (
                                <>
                                    {tab === 'news' && (
                                        <div className="flex flex-col gap-1.5">
                                            {news.length === 0 ? (
                                                <div className="text-[11px] text-center mt-4" style={{ color: 'var(--color-text-sub)' }}>ไม่มีข่าวล่าสุด</div>
                                            ) : (
                                                news.slice(0, 8).map((n: any, i: number) => (
                                                    <a
                                                        key={i}
                                                        href={n.url}
                                                        target="_blank"
                                                        rel="noreferrer"
                                                        className="flex flex-col gap-1 p-2 rounded-lg transition-colors"
                                                        onMouseEnter={(e) => (e.currentTarget.style.background = 'var(--color-hover)')}
                                                        onMouseLeave={(e) => (e.currentTarget.style.background = 'transparent')}
                                                    >
                                                        <span className="badge badge-violet flex-shrink-0 text-[10px] w-fit">{n.source}</span>
                                                        <span className="text-[11px] font-medium hover:underline">{n.title}</span>
                                                        <span className="text-[10px]" style={{ color: 'var(--color-text-sub)' }}>
                                                            {new Date(n.published_at).toLocaleDateString('th-TH', { month: 'short', day: 'numeric' })}
                                                        </span>
                                                    </a>
                                                ))
                                            )}
                                        </div>
                                    )}

                                    {tab === 'portfolio' && (
                                        <div>
                                            {!isAuthenticated ? (
                                                <div className="text-[11px] text-center py-4" style={{ color: 'var(--color-text-sub)' }}>
                                                    เข้าสู่ระบบเพื่อดูพอร์ตการลงทุน
                                                </div>
                                            ) : holding ? (
                                                <div className="flex flex-col gap-2">
                                                    {[
                                                        ['จำนวน', holding.qty?.toLocaleString() ?? '—'],
                                                        ['ต้นทุนเฉลี่ย', holding.avg_cost?.toFixed(2) ?? '—'],
                                                        ['มูลค่าปัจจุบัน', holding.current_value?.toFixed(2) ?? '—'],
                                                        ['กำไร/ขาดทุน%', holding.unrealized_pl_pct != null
                                                            ? `${holding.unrealized_pl_pct >= 0 ? '+' : ''}${holding.unrealized_pl_pct.toFixed(2)}%`
                                                            : '—'],
                                                    ].map(([label, val], i) => (
                                                        <div key={i} className="rounded-xl p-2.5 border" style={{ background: 'var(--color-input-bg)', borderColor: 'var(--color-border)' }}>
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
                                                <div className="text-[11px] text-center py-4" style={{ color: 'var(--color-text-sub)' }}>
                                                    ไม่มีหุ้น {displaySymbol(selectedStock?.sym)} ในพอร์ต
                                                </div>
                                            )}
                                        </div>
                                    )}

                                    {tab === 'notes' && (
                                        <div className="flex flex-col gap-2">
                                            {!isAuthenticated ? (
                                                <div className="text-[11px] text-center mt-4" style={{ color: 'var(--color-text-sub)' }}>
                                                    Login เพื่อบันทึก investment thesis
                                                </div>
                                            ) : (
                                                <>
                                                    <div className="flex items-center justify-between">
                                                        <span className="text-[10px]" style={{ color: 'var(--color-text-sub)' }}>
                                                            บันทึก thesis
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
                                                        className="w-full resize-none text-[11px] rounded-lg p-2 outline-none"
                                                        rows={8}
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
                                        <div className="flex flex-col gap-2">
                                            {funData.map(([k, v]) => (
                                                <div key={k} className="rounded-xl p-2.5 border" style={{ background: 'var(--color-input-bg)', borderColor: 'var(--color-border)' }}>
                                                    <div className="text-[10px] uppercase tracking-wider mb-1" style={{ color: 'var(--color-text-sub)' }}>{k}</div>
                                                    <div className="text-sm font-bold">{v}</div>
                                                </div>
                                            ))}
                                        </div>
                                    )}
                                </>
                            )}
                        </div>
                    )}
                </div>
            </aside>
        </>
    );
}
