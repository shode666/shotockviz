import { useState, useEffect } from 'react';
import { X } from 'lucide-react';
import stockService from '@/services/stockService';
import { extractErrorMessage } from '@/services/apiErrorHandler';
import { validateSrLevelPrice } from '@/utils/srLevelValidation';

// bd:shotockviz-474 — create a user-owned horizontal S/R level for the
// symbol currently on the chart. Horizontal only, by design (the removed
// toolbar covered trend/Fib/rectangle/arrow/pitchfork — none of that comes
// back here; see docs/engagements/ui-honesty-2026-09.md ADR-UH-002).

export interface AddSrLevelModalProps {
    isOpen: boolean;
    onClose: () => void;
    onSuccess: () => void;
    symbol: string;
    /** Last traded price, used only to default the level_type radio to
     * whichever side of price the user most likely means (resistance above,
     * support below) — a starting guess the user can always override, never
     * a validated fact. */
    lastPrice?: number | null;
}

type LevelType = 'support' | 'resistance';

export default function AddSrLevelModal({ isOpen, onClose, onSuccess, symbol, lastPrice }: AddSrLevelModalProps) {
    const [price, setPrice] = useState('');
    const [levelType, setLevelType] = useState<LevelType>('resistance');
    const [tag, setTag] = useState('');
    const [priceError, setPriceError] = useState('');
    const [submitError, setSubmitError] = useState('');
    const [saving, setSaving] = useState(false);

    useEffect(() => {
        if (isOpen) {
            setPrice(lastPrice != null ? String(lastPrice) : '');
            setLevelType('resistance');
            setTag('');
            setPriceError('');
            setSubmitError('');
        }
    }, [isOpen, lastPrice]);

    if (!isOpen) return null;

    const handleSubmit = async () => {
        const err = validateSrLevelPrice(price);
        if (err) {
            setPriceError(err);
            return;
        }
        setPriceError('');
        setSubmitError('');
        setSaving(true);
        try {
            await stockService.createSrLevel(symbol, {
                price: Number(price),
                level_type: levelType,
                tag: tag.trim() || undefined,
            });
            onClose();
            onSuccess();
        } catch (e: unknown) {
            setSubmitError(extractErrorMessage(e as any));
        } finally {
            setSaving(false);
        }
    };

    return (
        <div className="glass-overlay fixed inset-0 z-50 flex items-center justify-center" onClick={(e) => e.target === e.currentTarget && onClose()}>
            <div className="glass-panel rounded-2xl p-6 w-80 animate-slide-up">
                <div className="flex items-center justify-between mb-5">
                    <h3 className="font-bold">เพิ่มเส้นแนวนอน — {symbol}</h3>
                    <button onClick={onClose} aria-label="Close" style={{ color: 'var(--color-text-sub)' }}>
                        <X size={14} />
                    </button>
                </div>

                <div className="flex flex-col gap-3">
                    <div className="flex rounded-xl overflow-hidden" style={{ background: 'var(--color-input-bg)' }}>
                        {(['support', 'resistance'] as const).map((t) => (
                            <button
                                key={t}
                                onClick={() => setLevelType(t)}
                                aria-pressed={levelType === t}
                                className="flex-1 py-2 text-xs font-semibold transition-all cursor-pointer"
                                style={{
                                    background: levelType === t ? (t === 'support' ? '#eab308' : '#d946ef') : 'transparent',
                                    color: levelType === t ? '#fff' : 'var(--color-text-sub)',
                                }}
                            >
                                {t === 'support' ? 'Support' : 'Resistance'}
                            </button>
                        ))}
                    </div>

                    <div>
                        <label className="text-xs font-medium mb-1 block" style={{ color: 'var(--color-text-sub)' }} htmlFor="sr-level-price">
                            ราคา
                        </label>
                        <input
                            id="sr-level-price"
                            type="number"
                            step="any"
                            value={price}
                            onChange={(e) => { setPrice(e.target.value); setPriceError(''); }}
                            aria-invalid={!!priceError}
                            aria-describedby={priceError ? 'sr-level-price-error' : undefined}
                            className="w-full px-3 py-2 rounded-lg text-sm"
                            style={{ background: 'var(--color-input-bg)', border: priceError ? '1px solid var(--color-red)' : '1px solid transparent' }}
                        />
                        {priceError && (
                            <p id="sr-level-price-error" className="text-xs mt-1" style={{ color: 'var(--color-red)' }}>
                                {priceError}
                            </p>
                        )}
                    </div>

                    <div>
                        <label className="text-xs font-medium mb-1 block" style={{ color: 'var(--color-text-sub)' }} htmlFor="sr-level-tag">
                            ป้ายกำกับ (ไม่บังคับ) — เช่น entry / stop / target
                        </label>
                        <input
                            id="sr-level-tag"
                            type="text"
                            maxLength={50}
                            value={tag}
                            onChange={(e) => setTag(e.target.value)}
                            className="w-full px-3 py-2 rounded-lg text-sm"
                            style={{ background: 'var(--color-input-bg)', border: '1px solid transparent' }}
                        />
                    </div>

                    {submitError && (
                        <p className="text-xs" style={{ color: 'var(--color-red)' }} role="alert">
                            {submitError}
                        </p>
                    )}

                    <button
                        onClick={handleSubmit}
                        disabled={saving}
                        className="btn-accent rounded-lg py-2 text-sm font-semibold mt-1"
                        style={{ opacity: saving ? 0.6 : 1, cursor: saving ? 'not-allowed' : 'pointer' }}
                    >
                        {saving ? 'กำลังบันทึก…' : 'บันทึก'}
                    </button>
                </div>
            </div>
        </div>
    );
}
