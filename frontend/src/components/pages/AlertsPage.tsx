import { useState, useEffect, useCallback, useRef } from 'react';
import { Bell, BellPlus, X, Search, Loader2, CheckCircle2, Timer } from 'lucide-react';
import alertService from '@/services/alertService';
import stockService from '@/services/stockService';
import useAuthStore from '@/store/authStore';
import { displaySymbol, parseSymbol, MARKET_COLORS, MARKET_CURRENCY } from '@/utils/formatters';

const ALERT_TYPES = ['Price Above', 'Price Below', 'RSI Below', 'RSI Above', 'Golden Cross', 'Death Cross', 'Volume Spike'];
const PRICE_ALERT_TYPES = new Set(['Price Above', 'Price Below']);

// label has no glyph prefix — the status dot (rendered separately, see the
// `<div className="w-2 h-2 rounded-full" ...>` toggle button) already carries
// that signal; only "triggered" gets an extra lucide CheckCircle2 (bd:ux-2026-09
// icon rule — no emoji/unicode glyph as icon).
// Triggered uses --color-support (chart-level yellow) per 03-design-notes.md
// §Alerts "state ที่ 3 'แจ้งแล้ว' สี support-yellow" — distinct from --color-yellow.
const STATUS_STYLE = {
    active: { dot: 'var(--color-up)', label: 'ทำงานอยู่', color: 'var(--color-up)', Icon: null },
    triggered: { dot: 'var(--color-support)', label: 'แจ้งแล้ว', color: 'var(--color-support)', Icon: CheckCircle2 },
    inactive: { dot: 'var(--color-text-sub)', label: 'หยุดชั่วคราว', color: 'var(--color-text-sub)', Icon: null },
};

function formatTriggeredTime(iso?: string | null): string {
    if (!iso) return '';
    const d = new Date(iso);
    if (Number.isNaN(d.getTime())) return '';
    return d.toLocaleTimeString('th-TH', { hour: '2-digit', minute: '2-digit', hour12: false });
}

const EMPTY_FORM = { symbol: '', alert_type: 'Price Above', condition: 'above', value: '', channel: 'in_app' };

export default function AlertsPage() {
    const { isAuthenticated } = useAuthStore();
    const [alerts, setAlerts] = useState([]);
    const [loading, setLoading] = useState(false);
    const [timedOut, setTimedOut] = useState(false);
    const [showModal, setShowModal] = useState(false);
    const [form, setForm] = useState(EMPTY_FORM);
    const [saving, setSaving] = useState(false);

    // ─── Symbol autocomplete state ───
    const [searchQuery, setSearchQuery] = useState('');
    const [searchResults, setSearchResults] = useState<any[]>([]);
    const [searchLoading, setSearchLoading] = useState(false);
    const [showDropdown, setShowDropdown] = useState(false);
    const [selectedMarket, setSelectedMarket] = useState('');
    const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const dropdownRef = useRef<HTMLDivElement>(null);

    // Close dropdown on outside click
    useEffect(() => {
        const handler = (e: MouseEvent) => {
            if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
                setShowDropdown(false);
            }
        };
        document.addEventListener('mousedown', handler);
        return () => document.removeEventListener('mousedown', handler);
    }, []);

    // Debounced search
    useEffect(() => {
        if (!searchQuery.trim()) {
            setSearchResults([]);
            return;
        }
        setSearchLoading(true);
        if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
        searchTimerRef.current = setTimeout(async () => {
            try {
                const res = await stockService.search(searchQuery);
                setSearchResults(res.data?.results ?? res.data ?? []);
                setShowDropdown(true);
            } catch {
                setSearchResults([]);
            } finally {
                setSearchLoading(false);
            }
        }, 300);
        return () => { if (searchTimerRef.current) clearTimeout(searchTimerRef.current); };
    }, [searchQuery]);

    const handleSelectSymbol = (symbol: string, market?: string) => {
        const parsed = parseSymbol(symbol, market);
        setForm((f) => ({ ...f, symbol: symbol.toUpperCase() }));
        setSearchQuery(parsed.display);
        setSelectedMarket(parsed.market);
        setShowDropdown(false);
    };

    const isPriceAlert = PRICE_ALERT_TYPES.has(form.alert_type);
    const currency = MARKET_CURRENCY[selectedMarket] || MARKET_CURRENCY.US;
    const mktColors = MARKET_COLORS[selectedMarket] || MARKET_COLORS.US;

    const loadAlerts = useCallback(async () => {
        if (!isAuthenticated) return;
        setLoading(true);
        setTimedOut(false);
        try {
            const res = await alertService.getAll();
            setAlerts(res.data);
        } catch (err: any) {
            if (err?.code === 'ECONNABORTED' || err?.message?.includes('timeout')) {
                setTimedOut(true);
            }
        } finally {
            setLoading(false);
        }
    }, [isAuthenticated]);

    useEffect(() => { loadAlerts(); }, [loadAlerts]);

    const handleCreate = async () => {
        if (!form.symbol || !form.value) return;
        setSaving(true);
        try {
            await alertService.create({
                symbol: form.symbol.toUpperCase(),
                alert_type: form.alert_type,
                condition: form.condition,
                value: parseFloat(form.value),
                channel: form.channel,
            });
            setShowModal(false);
            setForm(EMPTY_FORM);
            setSearchQuery('');
            setSelectedMarket('');
            loadAlerts();
        } finally {
            setSaving(false);
        }
    };

    const handleDelete = async (id) => {
        try {
            await alertService.delete(id);
            setAlerts((prev) => prev.filter((a) => a.id !== id));
        } catch { /* ignore */ }
    };

    const handleToggle = async (id) => {
        try {
            const res = await alertService.toggle(id);
            setAlerts((prev) => prev.map((a) => a.id === id ? res.data : a));
        } catch { /* ignore */ }
    };

    const openModal = () => {
        setShowModal(true);
        setForm(EMPTY_FORM);
        setSearchQuery('');
        setSelectedMarket('');
        setSearchResults([]);
    };

    // Get currency for an alert's symbol
    const getAlertCurrency = (symbol: string) => {
        const parsed = parseSymbol(symbol);
        return MARKET_CURRENCY[parsed.market] || MARKET_CURRENCY.US;
    };

    return (
        <div className="flex-1 overflow-auto p-6" style={{ background: 'var(--color-bg)' }}>
            <div className="max-w-3xl mx-auto animate-fade-in">

                <div className="flex items-center justify-between mb-5">
                    <div>
                        <h2 className="text-base font-bold flex items-center gap-2"><Bell size={16} /> Price Alerts</h2>
                        <p className="text-xs mt-0.5" style={{ color: 'var(--color-text-sub)' }}>รับแจ้งเตือนเมื่อราคาถึงเป้าหมาย</p>
                    </div>
                    {isAuthenticated && (
                        <button onClick={openModal} className="btn-accent flex items-center gap-1.5"><BellPlus size={12} /> สร้าง Alert</button>
                    )}
                </div>

                {!isAuthenticated ? (
                    <div className="panel border rounded-2xl p-8 text-center" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                        <div className="mb-3 flex justify-center"><Bell size={32} style={{ color: 'var(--color-text-sub)' }} /></div>
                        <p className="text-sm font-medium mb-1">กรุณาเข้าสู่ระบบ</p>
                        <p className="text-xs" style={{ color: 'var(--color-text-sub)' }}>ต้อง Login เพื่อสร้างและจัดการ alerts</p>
                    </div>
                ) : loading ? (
                    <div className="flex flex-col gap-3">
                        {[1, 2, 3].map((i) => (
                            <div key={i} className="panel border rounded-2xl px-4 py-3 h-14 animate-pulse" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }} />
                        ))}
                    </div>
                ) : timedOut ? (
                    <div className="panel border rounded-2xl p-8 text-center animate-fade-in" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                        <Timer size={24} strokeWidth={2} className="mb-3 mx-auto" aria-hidden="true" style={{ color: 'var(--color-text-sub)' }} />
                        <p className="text-sm font-medium mb-1">Request timed out</p>
                        <p className="text-xs mb-4" style={{ color: 'var(--color-text-sub)' }}>ข้อมูลใช้เวลานานเกินไป — กรุณาลองใหม่</p>
                        <button onClick={loadAlerts} className="btn-accent">Retry</button>
                    </div>
                ) : alerts.length === 0 ? (
                    <div className="panel border rounded-2xl p-8 text-center" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                        <div className="mb-3 flex justify-center"><Bell size={32} style={{ color: 'var(--color-text-sub)' }} /></div>
                        <p className="text-sm font-medium mb-1">ยังไม่มี alert</p>
                        <p className="text-xs mb-4" style={{ color: 'var(--color-text-sub)' }}>กดปุ่ม "สร้าง Alert" เพื่อตั้งการแจ้งเตือน</p>
                        <button onClick={openModal} className="btn-accent flex items-center gap-1.5"><BellPlus size={12} /> สร้าง Alert</button>
                    </div>
                ) : (
                    <div className="flex flex-col gap-3">
                        {alerts.map((a) => {
                            const statusKey = a.status === 'TRIGGERED' ? 'triggered' : a.is_active ? 'active' : 'inactive';
                            const s = STATUS_STYLE[statusKey] || STATUS_STYLE.active;
                            const alertCurr = getAlertCurrency(a.symbol);
                            const alertParsed = parseSymbol(a.symbol);
                            const alertMktColors = MARKET_COLORS[alertParsed.market] || MARKET_COLORS.US;
                            const isPrice = a.alert_type?.includes('PRICE') || a.alert_type?.includes('Price');
                            return (
                                <div key={a.id} className="panel border rounded-2xl px-4 py-3 flex items-center gap-4" style={{ borderWidth: 1, borderStyle: 'solid', borderColor: 'var(--color-border)' }}>
                                    <button onClick={() => handleToggle(a.id)} className="flex-shrink-0" aria-label={s.label}>
                                        <div className={`w-2 h-2 rounded-full ${statusKey === 'active' ? 'animate-pulse-dot' : ''}`} style={{ background: s.dot }} aria-hidden="true" />
                                    </button>
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2">
                                            <span className="text-sm font-bold" style={{ color: 'var(--color-accent-text)' }}>{displaySymbol(a.symbol)}</span>
                                            <span className="badge text-[9px]" style={{ background: alertMktColors.bg, color: alertMktColors.text }}>{alertParsed.market}</span>
                                            <span className="badge badge-violet">{a.alert_type}</span>
                                        </div>
                                        <div className="text-[11px] mt-0.5 truncate" style={{ color: 'var(--color-text-sub)' }}>
                                            เงื่อนไข: {a.condition} {isPrice ? `${alertCurr.sign}${a.value}` : a.value} · via {a.channel}
                                            <span className="ml-1.5 text-[9px] px-1 py-0.5 rounded" style={{ background: 'var(--color-hover)' }}>{alertCurr.code}</span>
                                        </div>
                                    </div>
                                    <div className="text-right flex-shrink-0">
                                        <div className="text-[11px] mb-0.5 flex items-center justify-end gap-1 font-semibold" style={{ color: s.color }}>
                                            {s.Icon && <s.Icon size={11} strokeWidth={2} aria-hidden="true" />}
                                            {s.label}
                                            {statusKey === 'triggered' && a.triggered_at && ` ${formatTriggeredTime(a.triggered_at)}`}
                                        </div>
                                    </div>
                                    <button onClick={() => handleDelete(a.id)} aria-label={`ลบ alert ${displaySymbol(a.symbol)}`} className="text-xs px-2 py-1 rounded-lg transition-colors" style={{ color: 'var(--color-text-sub)' }}
                                        onMouseEnter={(e) => { e.currentTarget.style.background = 'var(--color-down-muted)'; e.currentTarget.style.color = 'var(--color-down)' }}
                                        onMouseLeave={(e) => { e.currentTarget.style.background = 'transparent'; e.currentTarget.style.color = 'var(--color-text-sub)' }}><X size={12} /></button>
                                </div>
                            );
                        })}
                    </div>
                )}
            </div>

            {/* ─── Create Alert Modal ─── */}
            {showModal && (
                <div className="glass-overlay fixed inset-0 z-50 flex items-center justify-center" onClick={(e) => e.target === e.currentTarget && setShowModal(false)}>
                    <div className="glass-panel rounded-2xl p-6 w-96 animate-slide-up">
                        <div className="flex items-center justify-between mb-5">
                            <h3 className="font-bold">สร้าง Alert ใหม่</h3>
                            <button onClick={() => setShowModal(false)} style={{ color: 'var(--color-text-sub)' }}><X size={14} /></button>
                        </div>
                        <div className="flex flex-col gap-3">

                            {/* Symbol with Autocomplete */}
                            <div ref={dropdownRef} className="relative">
                                <div className="text-[10px] uppercase tracking-wider mb-1.5 flex items-center gap-2" style={{ color: 'var(--color-text-sub)' }}>
                                    Symbol
                                    {selectedMarket && (
                                        <span className="badge text-[9px] px-1.5 py-0.5" style={{ background: mktColors.bg, color: mktColors.text }}>
                                            {selectedMarket} · {currency.code}
                                        </span>
                                    )}
                                </div>
                                <div className="input-field flex items-center gap-2 p-0 overflow-hidden">
                                    <Search size={12} className="ml-3 shrink-0" style={{ color: 'var(--color-text-sub)' }} />
                                    <input
                                        type="text"
                                        className="flex-1 bg-transparent outline-none pr-3 py-2 text-sm"
                                        placeholder="ค้นหา เช่น PTT, AAPL, 7203.T..."
                                        value={searchQuery}
                                        onChange={(e) => {
                                            setSearchQuery(e.target.value);
                                            if (!e.target.value.trim()) {
                                                setForm((f) => ({ ...f, symbol: '' }));
                                                setSelectedMarket('');
                                            }
                                        }}
                                        onFocus={() => searchResults.length > 0 && setShowDropdown(true)}
                                        onKeyDown={(e) => {
                                            if (e.key === 'Enter' && searchQuery.trim()) {
                                                handleSelectSymbol(searchQuery.trim());
                                            }
                                        }}
                                    />
                                    {searchLoading && (
                                        <Loader2 size={12} className="mr-3 shrink-0 animate-spin" style={{ color: 'var(--color-text-sub)' }} />
                                    )}
                                </div>

                                {/* Autocomplete Dropdown */}
                                {showDropdown && searchResults.length > 0 && (
                                    <div className="glass-dropdown absolute left-0 right-0 z-50 rounded-xl overflow-hidden mt-1" style={{ maxHeight: 220, overflowY: 'auto' }}>
                                        {searchResults.slice(0, 6).map((r) => {
                                            const parsed = parseSymbol(r.symbol, r.market);
                                            const mkt = r.market || parsed.market;
                                            const colors = MARKET_COLORS[mkt] || MARKET_COLORS.US;
                                            const curr = MARKET_CURRENCY[mkt] || MARKET_CURRENCY.US;
                                            return (
                                                <button
                                                    key={r.symbol}
                                                    onClick={() => handleSelectSymbol(r.symbol, r.market)}
                                                    className="w-full flex items-center justify-between px-3 py-2 text-left transition-colors hover:bg-[var(--color-hover)]"
                                                >
                                                    <div className="flex-1 min-w-0">
                                                        <div className="text-[11px] font-semibold" style={{ color: 'var(--color-text)' }}>{parsed.display}</div>
                                                        <div className="text-[10px] truncate" style={{ color: 'var(--color-text-sub)', maxWidth: 160 }}>
                                                            {r.name_th || r.name}
                                                        </div>
                                                    </div>
                                                    <div className="flex items-center gap-1.5 flex-shrink-0 ml-2">
                                                        <span className="badge text-[9px]" style={{ background: colors.bg, color: colors.text }}>{mkt}</span>
                                                        <span className="text-[9px]" style={{ color: 'var(--color-text-sub)' }}>{curr.code}</span>
                                                    </div>
                                                </button>
                                            );
                                        })}
                                    </div>
                                )}

                                {/* Direct add when no results */}
                                {showDropdown && searchQuery.trim() && !searchLoading && searchResults.length === 0 && (
                                    <div className="glass-dropdown absolute left-0 right-0 z-50 rounded-xl overflow-hidden mt-1">
                                        <button
                                            onClick={() => handleSelectSymbol(searchQuery.trim())}
                                            className="w-full flex items-center gap-2 px-3 py-2.5 text-left transition-colors hover:bg-[var(--color-hover)]"
                                        >
                                            <Search size={12} style={{ color: 'var(--color-accent)', flexShrink: 0 }} />
                                            <div>
                                                <div className="text-[11px] font-semibold" style={{ color: 'var(--color-text)' }}>
                                                    ใช้ {searchQuery.trim().toUpperCase()} โดยตรง
                                                </div>
                                                <div className="text-[10px]" style={{ color: 'var(--color-text-sub)', opacity: 0.7 }}>
                                                    ไม่พบในฐานข้อมูล · ใช้ ticker โดยตรง
                                                </div>
                                            </div>
                                        </button>
                                    </div>
                                )}
                            </div>

                            {/* Alert Type */}
                            <div>
                                <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: 'var(--color-text-sub)' }}>ประเภท Alert</div>
                                <select className="input-field glass-select" value={form.alert_type} onChange={(e) => setForm((f) => ({ ...f, alert_type: e.target.value, condition: e.target.value.includes('Above') ? 'above' : 'below' }))}>
                                    {ALERT_TYPES.map((t) => <option key={t}>{t}</option>)}
                                </select>
                            </div>

                            {/* Value with currency prefix for price alerts */}
                            <div>
                                <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: 'var(--color-text-sub)' }}>
                                    ค่าเงื่อนไข {isPriceAlert && selectedMarket && <span className="text-[9px] ml-1" style={{ color: 'var(--color-accent-text)' }}>({currency.code})</span>}
                                </div>
                                {isPriceAlert && selectedMarket ? (
                                    <div className="input-field flex items-center gap-2 p-0 overflow-hidden">
                                        <span className="pl-3 text-xs font-medium shrink-0 select-none" style={{ color: 'var(--color-text-sub)' }}>
                                            {currency.sign}
                                        </span>
                                        <input
                                            type="number"
                                            className="flex-1 bg-transparent outline-none pr-3 py-2 text-sm"
                                            placeholder="เช่น 40.00"
                                            value={form.value}
                                            onChange={(e) => setForm((f) => ({ ...f, value: e.target.value }))}
                                        />
                                    </div>
                                ) : (
                                    <input
                                        type="number"
                                        className="input-field"
                                        placeholder={isPriceAlert ? 'เช่น 40.00' : 'เช่น 30 (RSI)'}
                                        value={form.value}
                                        onChange={(e) => setForm((f) => ({ ...f, value: e.target.value }))}
                                    />
                                )}
                            </div>

                            {/* Channel */}
                            <div>
                                <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: 'var(--color-text-sub)' }}>ช่องทางแจ้งเตือน</div>
                                <select className="input-field glass-select" value={form.channel} onChange={(e) => setForm((f) => ({ ...f, channel: e.target.value }))}>
                                    <option value="in_app">In-App</option>
                                    <option value="telegram">Telegram</option>
                                </select>
                            </div>

                            <div className="flex gap-2 mt-2">
                                <button onClick={() => setShowModal(false)} className="btn-outline flex-1 py-2">ยกเลิก</button>
                                <button onClick={handleCreate} disabled={saving} className="btn-accent flex-1 py-2">{saving ? 'กำลังบันทึก…' : 'สร้าง Alert'}</button>
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    );
}
