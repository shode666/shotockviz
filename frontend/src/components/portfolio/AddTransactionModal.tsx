import { useState, useEffect, useRef } from 'react';
import { TrendingUp, TrendingDown, X, Search, Loader2 } from 'lucide-react';
import portfolioService from '@/services/portfolioService';
import stockService from '@/services/stockService';
import { displaySymbol, parseSymbol, MARKET_COLORS, MARKET_CURRENCY } from '@/utils/formatters';
import { validateTransactionForm } from '@/utils/formValidation';
import { extractErrorMessage } from '@/services/apiErrorHandler';
import { buildTransactionUpdatePatch } from '@/utils/transactionEditDiff';

// bd:shotockviz-gij — the saved row this modal is editing, or undefined/null
// for "add new". Matches what portfolioService.getTransactions() rows carry
// (PortfolioPage.tsx's `txns`) and what TransactionUpdate (backend/models/
// schemas.py:167-175) can actually persist: qty/price/fee/currency/date/note.
// `type` (BUY/SELL) is NOT in TransactionUpdate — symbol and type render
// read-only in edit mode rather than offering controls the PUT would ignore.
export interface EditableTransaction {
    id: number | string;
    symbol: string;
    type: 'BUY' | 'SELL';
    qty: number;
    price: number;
    fee?: number | null;
    currency?: string | null;
    date: string;
    note?: string | null;
}

interface AddTransactionModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: () => void;
    transaction?: EditableTransaction | null;
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

export function AddTransactionModal({ isOpen, onClose, onSuccess, transaction }: AddTransactionModalProps) {
    const isEditMode = !!transaction;
    const [form, setForm] = useState<TransactionForm>(TXN_FORM_INIT);
    const [saving, setSaving] = useState(false);
    const [formErrors, setFormErrors] = useState<Record<string, string>>({});
    // bd:shotockviz-gij — surfaces the 409 currency-conflict rejection (and
    // any other PUT failure) inline, in addition to the global toast api.ts
    // already fires for any non-silent-path error — so the failure is never
    // silent AND the modal stays open with the reason visible next to Save.
    const [submitError, setSubmitError] = useState('');

    // ─── Symbol autocomplete state ───
    const [searchQuery, setSearchQuery] = useState('');
    const [searchResults, setSearchResults] = useState<any[]>([]);
    const [searchLoading, setSearchLoading] = useState(false);
    const [showDropdown, setShowDropdown] = useState(false);
    const [selectedMarket, setSelectedMarket] = useState('');
    const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
    const dropdownRef = useRef<HTMLDivElement>(null);

    // Reset / prefill form whenever the modal opens — for either mode.
    useEffect(() => {
        if (isOpen) {
            if (transaction) {
                setForm({
                    symbol: transaction.symbol,
                    type: transaction.type,
                    qty: String(transaction.qty),
                    price: String(transaction.price),
                    fee: String(transaction.fee ?? 0),
                    currency: transaction.currency === 'USD' ? 'USD' : 'THB',
                    date: transaction.date,
                    note: transaction.note || '',
                });
                setSelectedMarket(parseSymbol(transaction.symbol).market);
            } else {
                setForm(TXN_FORM_INIT);
                setSelectedMarket('');
            }
            setFormErrors({});
            setSubmitError('');
            setSearchQuery('');
            setSearchResults([]);
            setShowDropdown(false);
        }
    }, [isOpen, transaction]);

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

    // bd:shotockviz-gij — one handler, two backend calls. Edit mode never
    // sends `fx_rate`: TransactionUpdate treats it as an explicit correction,
    // never a recomputed side effect of editing qty/price/date
    // (backend/api/routes/portfolio.py:399-402) — omitting the key entirely
    // (not resending the old value) is what keeps that promise from this
    // side, since `model_dump(exclude_unset=True)` only touches keys present
    // in the request body.
    const handleSubmit = async () => {
        const errors = validateTransactionForm({ symbol: form.symbol, qty: form.qty, price: form.price });
        if (Object.keys(errors).length > 0) {
            setFormErrors(errors);
            return;
        }
        setFormErrors({});
        setSubmitError('');
        setSaving(true);
        try {
            if (isEditMode && transaction) {
                const patch = buildTransactionUpdatePatch(transaction, form);
                if (Object.keys(patch).length > 0) {
                    await portfolioService.updateTransaction(transaction.id, patch);
                }
            } else {
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
            }
            onClose();
            onSuccess();
        } catch (err: any) {
            // bd:shotockviz-7ju — this is where a currency-conflict 409 on
            // update surfaces: extractErrorMessage reads the enveloped
            // {data:null, meta:{error:{message}}} body (schemas/envelope.py),
            // the same extraction api.ts's global interceptor already uses
            // for the toast, so the two never disagree.
            setSubmitError(extractErrorMessage(err));
        } finally {
            setSaving(false);
        }
    };

    if (!isOpen) return null;

    return (
        <div className="glass-overlay fixed inset-0 z-50 flex items-center justify-center" onClick={(e) => e.target === e.currentTarget && onClose()}>
            <div className="glass-panel rounded-2xl p-6 w-96 animate-slide-up">
                <div className="flex items-center justify-between mb-5">
                    <h3 className="font-bold">{isEditMode ? 'แก้ไขธุรกรรม' : 'เพิ่มธุรกรรม'}</h3>
                    <button onClick={onClose} style={{ color: 'var(--color-text-sub)' }}>
                        <X size={14} />
                    </button>
                </div>

                <div className="flex flex-col gap-3">
                    {/* Type Toggle — bd:shotockviz-gij: TransactionUpdate has no `type`
                        field (backend/models/schemas.py:167-175), so editing can't
                        change BUY/SELL. Disabled + labelled rather than silently
                        accepting a click that would never be sent to the server. */}
                    <div className="flex rounded-xl overflow-hidden" style={{ background: 'var(--color-input-bg)', opacity: isEditMode ? 0.6 : 1 }}>
                        {(['BUY', 'SELL'] as const).map((t) => (
                            <button
                                key={t}
                                onClick={() => !isEditMode && setForm((f) => ({ ...f, type: t }))}
                                disabled={isEditMode}
                                aria-disabled={isEditMode}
                                title={isEditMode ? 'เปลี่ยนประเภทซื้อ/ขายไม่ได้ — ลบแล้วสร้างใหม่หากต้องการเปลี่ยน' : undefined}
                                className="flex-1 py-2 text-xs font-semibold transition-all flex items-center justify-center gap-1.5"
                                style={{
                                    background: form.type === t
                                        ? (t === 'BUY' ? 'var(--color-green)' : 'var(--color-red)')
                                        : 'transparent',
                                    color: form.type === t ? '#fff' : 'var(--color-text-sub)',
                                    cursor: isEditMode ? 'not-allowed' : 'pointer',
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
                    {isEditMode && (
                        <p className="text-[10px] -mt-2" style={{ color: 'var(--color-text-sub)' }}>
                            เปลี่ยน symbol หรือประเภทซื้อ/ขายไม่ได้ — ลบแล้วสร้างใหม่หากต้องการเปลี่ยน
                        </p>
                    )}

                    {/* Symbol — bd:shotockviz-gij: same reason as Type above, read-only
                        in edit mode instead of the create form's search box. */}
                    {isEditMode ? (
                        <div>
                            <div className="text-[10px] uppercase tracking-wider mb-1.5 flex items-center gap-2" style={{ color: 'var(--color-text-sub)' }}>
                                Symbol
                                {selectedMarket && (
                                    <span className="badge text-[9px] px-1.5 py-0.5" style={{ background: mktColors.bg, color: mktColors.text }}>
                                        {selectedMarket}
                                    </span>
                                )}
                            </div>
                            <div className="input-field flex items-center gap-2 py-2 px-3">
                                <span className="text-sm font-semibold" style={{ color: 'var(--color-text)' }}>{displaySymbol(form.symbol)}</span>
                            </div>
                        </div>
                    ) : (
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
                                aria-invalid={!!formErrors.symbol}
                                aria-describedby={formErrors.symbol ? 'txn-symbol-error' : undefined}
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
                        {formErrors.symbol && (
                            <p id="txn-symbol-error" role="alert" className="text-[10px] mt-1" style={{ color: 'var(--color-red)' }}>{formErrors.symbol}</p>
                        )}

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
                    )}

                    {/* Currency Toggle — bd:shotockviz-gij: TransactionUpdate DOES accept
                        `currency`, and the backend re-runs the same rule-5 consistency
                        check on update (backend/api/routes/portfolio.py:405-414), so this
                        stays editable and can 409 in edit mode too (surfaced below the
                        Save button via submitError). */}
                    <div>
                        <div className="text-[10px] uppercase tracking-wider mb-1.5 flex items-center gap-1.5" style={{ color: 'var(--color-text-sub)' }}>
                            สกุลเงิน
                            <span className="text-[9px] px-1.5 py-0.5 rounded" style={{ background: 'var(--color-hover)', color: 'var(--color-text-sub)' }}>
                                {isEditMode ? 'ต้องตรงกับรายการอื่นของ symbol นี้' : 'auto-detect จาก symbol'}
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
                            aria-invalid={!!formErrors.qty}
                            aria-describedby={formErrors.qty ? 'txn-qty-error' : undefined}
                            onChange={(e) => setForm((f) => ({ ...f, qty: e.target.value }))}
                        />
                        {formErrors.qty && (
                            <p id="txn-qty-error" role="alert" className="text-[10px] mt-1" style={{ color: 'var(--color-red)' }}>{formErrors.qty}</p>
                        )}
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
                                aria-invalid={!!formErrors.price}
                                aria-describedby={formErrors.price ? 'txn-price-error' : undefined}
                                onChange={(e) => setForm((f) => ({ ...f, price: e.target.value }))}
                            />
                        </div>
                        {formErrors.price && (
                            <p id="txn-price-error" role="alert" className="text-[10px] mt-1" style={{ color: 'var(--color-red)' }}>{formErrors.price}</p>
                        )}
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

                    {/* วันที่ — disabled in edit mode. bd:shotockviz-qml fixed the server's
                        422 on TransactionUpdate.date, so that is no longer why this is
                        locked. It stays locked on Dave#8's evidence (bd:shotockviz-q5s):
                        realized P&L is recomputed from the whole date-ordered transaction
                        list on every read (portfolio_service.py), so moving one date
                        silently shifts realized figures book-wide; and an edit never
                        re-validates fx_rate against the bd:shotockviz-fnn observation-window
                        rule, so moving a trade out of the window it was priced under would
                        leave a rate the system's own rule says should not exist for that
                        date. Only lift this once both are handled. */}
                    <div>
                        <div className="text-[10px] uppercase tracking-wider mb-1.5" style={{ color: 'var(--color-text-sub)' }}>
                            วันที่
                        </div>
                        <input
                            type="date"
                            className="input-field"
                            value={form.date}
                            disabled={isEditMode}
                            aria-disabled={isEditMode}
                            style={isEditMode ? { opacity: 0.6, cursor: 'not-allowed' } : undefined}
                            onChange={(e) => setForm((f) => ({ ...f, date: e.target.value }))}
                        />
                        {isEditMode && (
                            <p className="text-[10px] mt-1" style={{ color: 'var(--color-text-sub)' }}>
                                แก้ไขวันที่ไม่ได้ — กำไรที่รับรู้แล้วคำนวณจากลำดับวันที่ของธุรกรรมทั้งหมด
                                การขยับวันที่รายการเดียวจะกระทบตัวเลขย้อนหลังทั้งพอร์ต ลบแล้วสร้างใหม่หากต้องการเปลี่ยนวันที่
                            </p>
                        )}
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

                    {submitError && (
                        <p role="alert" className="text-[10px]" style={{ color: 'var(--color-red)' }}>{submitError}</p>
                    )}

                    <div className="flex gap-2 mt-2">
                        <button onClick={onClose} className="btn-outline flex-1 py-2">
                            ยกเลิก
                        </button>
                        <button
                            onClick={handleSubmit}
                            disabled={saving}
                            className="btn-accent flex-1 py-2"
                        >
                            {saving ? 'กำลังบันทึก…' : (isEditMode ? 'บันทึกการแก้ไข' : 'บันทึก')}
                        </button>
                    </div>
                </div>
            </div>
        </div>
    );
}
