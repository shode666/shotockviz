import { useState, useEffect, useRef } from 'react';
import toast from 'react-hot-toast';
import { TrendingUp, TrendingDown, X, Search, Loader2 } from 'lucide-react';
import portfolioService from '@/services/portfolioService';
import stockService from '@/services/stockService';
import { parseSymbol, MARKET_COLORS, MARKET_CURRENCY } from '@/utils/formatters';

interface AddTransactionModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: () => void;
}

interface TransactionForm {
    symbol: string;
    type: 'BUY' | 'SELL';
    qty: string;
    price: string;
    fee: string;
    currency: 'THB' | 'USD';
    date: string;
    note: string;
}

const TXN_FORM_INIT: TransactionForm = {
    symbol: '',
    type: 'BUY',
    qty: '',
    price: '',
    fee: '0',
    currency: 'THB',
    date: new Date().toISOString().slice(0, 10),
    note: '',
};

// Map market currency code to form currency type
const toCurrencyType = (code: string): 'THB' | 'USD' => {
    if (code === 'THB') return 'THB';
    return 'USD'; // Default to USD for all non-THB markets
};

export function AddTransactionModal({ isOpen, onClose, onSuccess }: AddTransactionModalProps) {
    const [form, setForm] = useState<TransactionForm>(TXN_FORM_INIT);
    const [saving, setSaving] = useState(false);

    // ─── Symbol autocomplete state ───
    const [searchQuery, setSearchQuery] = useState('');
    const [searchResults, setSearchResults] = useState<any[]>([]);
    const [searchLoading, setSearchLoading] = useState(false);
    const [showDropdown, setShowDropdown] = useState(false);
    const [selectedMarket, setSelectedMarket] = useState('');
    const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const dropdownRef = useRef<HTMLDivElement>(null);

    // Reset form when modal opens
    useEffect(() => {
        if (isOpen) {
            setForm(TXN_FORM_INIT);
            setSearchQuery('');
            setSelectedMarket('');
            setSearchResults([]);
            setShowDropdown(false);
        }
    }, [isOpen]);

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
        const mkt = market || parsed.market;
        const curr = MARKET_CURRENCY[mkt] || MARKET_CURRENCY.US;
        setForm((f) => ({
            ...f,
            symbol: symbol.toUpperCase(),
            currency: toCurrencyType(curr.code),
        }));
        setSearchQuery(parsed.display);
        setSelectedMarket(mkt);
        setShowDropdown(false);
    };

    const mktColors = MARKET_COLORS[selectedMarket] || MARKET_COLORS.US;
    const currency = MARKET_CURRENCY[selectedMarket] || MARKET_CURRENCY[form.currency === 'THB' ? 'SET' : 'US'];
    const currSign = currency.sign;

    const handleAdd = async () => {
        if (!form.symbol || !form.qty || !form.price) return;
        setSaving(true);
        try {
            await portfolioService.addTransaction({
                symbol: form.symbol.toUpperCase(),
                type: form.type,
                qty: parseFloat(form.qty),
                price: parseFloat(form.price),
                fee: parseFloat(form.fee) || 0,
                currency: form.currency,
                date: form.date,
                note: form.note,
            });
            onClose();
            setForm(TXN_FORM_INIT);
            setSearchQuery('');
            setSelectedMarket('');
            onSuccess();
        } catch (err: any) {
            const msg = err?.response?.data?.detail || err?.message || 'เพิ่มธุรกรรมไม่สำเร็จ';
            toast.error(msg);
            console.error('[AddTransactionModal] Add failed:', err);
        } finally {
            setSaving(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="glass-overlay fixed inset-0 z-50 flex items-center justify-center" onClick={(e) => e.target === e.currentTarget && onClose()}>
            <div className="glass-panel rounded-2xl p-6 w-96 animate-slide-up">
                <div className="flex items-center justify-between mb-5">
                    <h3 className="font-bold">เพิ่มธุรกรรม</h3>
                    <button onClick={onClose} style={{ color: 'var(--color-text-sub)' }}>
                        <X size={14} />
                    </button>
                </div>

                <div className="flex flex-col gap-3">
                    {/* Type Toggle */}
                    <div className="flex rounded-xl overflow-hidden" style={{ background: 'var(--color-input-bg)' }}>
                        {(['BUY', 'SELL'] as const).map((t) => (
                            <button
                                key={t}
                                onClick={() => setForm((f) => ({ ...f, type: t }))}
                                className="flex-1 py-2 text-xs font-semibold transition-all flex items-center justify-center gap-1.5"
                                style={{
                                    background: form.type === t
                                        ? (t === 'BUY' ? 'var(--color-green)' : 'var(--color-red)')
                                        : 'transparent',
                                    color: form.type === t ? '#fff' : 'var(--color-text-sub)',
                                }}
                            >
                                {t === 'BUY' ? (
                                    <><TrendingUp size={12} /> ซื้อ</>
                                ) : (
                                    <><TrendingDown size={12} /> ขาย</>
                                )}
                            </button>
                        ))}
                    </div>

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

                    {/* Currency Toggle (auto-detected from symbol) */}
                    <div>
                        <div className="text-[10px] uppercase tracking-wider mb-1.5 flex items-center gap-1.5" style={{ color: 'var(--color-text-sub)' }}>
                            สกุลเงิน
                            <span className="text-[9px] px-1.5 py-0.5 rounded" style={{ background: 'var(--color-hover)', color: 'var(--color-text-sub)' }}>
                                auto-detect จาก symbol
                            </span>
                        </div>
                        <div className="flex rounded-xl overflow-hidden" style={{ background: 'var(--color-input-bg)' }}>
                            {(['THB', 'USD'] as const).map((c) => (
                                <button
                                    key={c}
                                    onClick={() => setForm((f) => ({ ...f, currency: c }))}
                                    className="flex-1 py-2 text-xs font-semibold transition-all"
                                    style={{
                                        background: form.currency === c ? 'var(--color-accent)' : 'transparent',
                                        color: form.currency === c ? '#fff' : 'var(--color-text-sub)',
                                    }}
                                >
                                    {c === 'THB' ? '฿ THB' : '$ USD'}
                                </button>
                            ))}
                        </div>
                    </div>

                    {/* จำนวน */}
                    <div>
                        <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: 'var(--color-text-sub)' }}>
                            จำนวน (หุ้น)
                        </div>
                        <input
                            type="number"
                            className="input-field"
                            placeholder="100"
                            value={form.qty}
                            onChange={(e) => setForm((f) => ({ ...f, qty: e.target.value }))}
                        />
                    </div>

                    {/* ราคาต่อหุ้น พร้อม currency prefix */}
                    <div>
                        <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: 'var(--color-text-sub)' }}>
                            ราคาต่อหุ้น
                        </div>
                        <div className="input-field flex items-center gap-2 p-0 overflow-hidden">
                            <span className="pl-3 text-xs font-medium shrink-0 select-none" style={{ color: 'var(--color-text-sub)' }}>
                                {currSign}
                            </span>
                            <input
                                type="number"
                                className="flex-1 bg-transparent outline-none pr-3 py-2 text-sm"
                                placeholder="38.00"
                                value={form.price}
                                onChange={(e) => setForm((f) => ({ ...f, price: e.target.value }))}
                            />
                        </div>
                    </div>

                    {/* ค่าคอมมิชชั่น */}
                    <div>
                        <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: 'var(--color-text-sub)' }}>
                            ค่าคอมมิชชั่น
                        </div>
                        <div className="input-field flex items-center gap-2 p-0 overflow-hidden">
                            <span className="pl-3 text-xs font-medium shrink-0 select-none" style={{ color: 'var(--color-text-sub)' }}>
                                {currSign}
                            </span>
                            <input
                                type="number"
                                className="flex-1 bg-transparent outline-none pr-3 py-2 text-sm"
                                placeholder="0"
                                value={form.fee}
                                onChange={(e) => setForm((f) => ({ ...f, fee: e.target.value }))}
                            />
                        </div>
                    </div>

                    {/* วันที่ */}
                    <div>
                        <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: 'var(--color-text-sub)' }}>
                            วันที่
                        </div>
                        <input
                            type="date"
                            className="input-field"
                            value={form.date}
                            onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))}
                        />
                    </div>

                    {/* หมายเหตุ */}
                    <div>
                        <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: 'var(--color-text-sub)' }}>
                            หมายเหตุ
                        </div>
                        <input
                            type="text"
                            className="input-field"
                            placeholder="เช่น ซื้อตามแผน DCA"
                            value={form.note}
                            onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))}
                        />
                    </div>

                    <div className="flex gap-2 mt-2">
                        <button onClick={onClose} className="btn-outline flex-1 py-2">
                            ยกเลิก
                        </button>
                        <button
                            onClick={handleAdd}
                            disabled={saving}
                            className="btn-accent flex-1 py-2"
                        >
                            {saving ? 'กำลังบันทึก…' : 'บันทึก'}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
