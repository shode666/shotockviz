import { useState, useEffect, useRef } from 'react';
import { Plus, Loader2, X } from 'lucide-react';
import stockService from '@/services/stockService';
import { parseSymbol, MARKET_COLORS } from '@/utils/formatters';

interface WatchlistSearchProps {
    /**
     * Called when user selects a stock from search results or adds directly.
     * @param sym - The stock symbol (uppercase, e.g., "NVDA" or "PTT.BK")
     */
    onSelect: (sym: string) => void;
    /**
     * Called when user closes the search UI.
     */
    onCancel: () => void;
}

/**
 * WatchlistSearch component
 *
 * Provides a search dropdown UI with autocomplete for searching and adding stocks.
 * Features:
 * - Debounced search (300ms)
 * - Market badges (US, SET, FUND, etc.)
 * - Direct add if symbol not found
 * - Thai/English name display
 *
 * Usage:
 *   <WatchlistSearch onSelect={(sym) => { ... }} onCancel={() => { ... }} />
 */
export function WatchlistSearch({ onSelect, onCancel }: WatchlistSearchProps) {
    const [searchQuery, setSearchQuery] = useState('');
    const [searchResults, setSearchResults] = useState<any[]>([]);
    const [searchLoading, setSearchLoading] = useState(false);
    const searchTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

    // Debounced search — 300ms delay
    useEffect(() => {
        if (!searchQuery.trim()) {
            setSearchResults([]);
            return;
        }
        setSearchLoading(true);
        clearTimeout(searchTimerRef.current ?? undefined);
        searchTimerRef.current = setTimeout(async () => {
            try {
                const res = await stockService.search(searchQuery);
                setSearchResults(res.data?.results ?? res.data ?? []);
            } catch {
                setSearchResults([]);
            } finally {
                setSearchLoading(false);
            }
        }, 300);

        return () => clearTimeout(searchTimerRef.current ?? undefined);
    }, [searchQuery]);

    const handleSelect = (sym: string) => {
        onSelect(sym);
    };

    const handleAddDirect = () => {
        const sym = searchQuery.trim().toUpperCase();
        if (sym) {
            onSelect(sym);
        }
    };

    return (
        <div className="relative border-b" style={{ borderColor: 'var(--color-border)' }}>
            <div className="px-3 py-2 flex gap-1 items-center">
                <div className="relative flex-1">
                    <input
                        autoFocus
                        className="input-field text-xs py-1 w-full pr-6"
                        placeholder="PTT.BK, AAPL..."
                        value={searchQuery}
                        onChange={(e) => setSearchQuery(e.target.value)}
                        onKeyDown={(e) => {
                            if (e.key === 'Enter') handleAddDirect();
                            if (e.key === 'Escape') onCancel();
                        }}
                    />
                    {searchLoading && (
                        <Loader2 size={11} className="absolute right-2 top-1/2 -translate-y-1/2 animate-spin" style={{ color: 'var(--color-text-sub)' }} />
                    )}
                </div>
                <button onClick={onCancel} className="p-1 rounded hover:bg-[var(--color-hover)] transition-colors" style={{ color: 'var(--color-text-sub)' }}>
                    <X size={12} />
                </button>
            </div>

            {/* Autocomplete dropdown */}
            {/* Show "add directly" button when: query typed, not loading, search returned empty */}
            {searchQuery.trim() && !searchLoading && searchResults.length === 0 && (
                <div
                    className="glass-dropdown absolute left-0 right-0 z-50 rounded-b-xl overflow-hidden"
                    style={{ top: '100%' }}
                >
                    <button
                        onClick={handleAddDirect}
                        className="w-full flex items-center gap-2 px-3 py-2.5 text-left transition-colors hover:bg-[var(--color-hover)]"
                    >
                        <Plus size={12} style={{ color: 'var(--color-accent)', flexShrink: 0 }} />
                        <div>
                            <div className="text-[11px] font-semibold" style={{ color: 'var(--color-text)' }}>
                                เพิ่ม {searchQuery.trim().toUpperCase()} โดยตรง
                            </div>
                            <div className="text-[10px]" style={{ color: 'var(--color-text-sub)', opacity: 0.7 }}>
                                ไม่พบในฐานข้อมูล · เพิ่มด้วย ticker โดยตรง
                            </div>
                        </div>
                    </button>
                </div>
            )}

            {/* Search results dropdown */}
            {searchResults.length > 0 && (
                <div
                    className="glass-dropdown absolute left-0 right-0 z-50 rounded-b-xl overflow-hidden"
                    style={{ top: '100%' }}
                >
                    {searchResults.slice(0, 6).map((r) => {
                        const parsed = parseSymbol(r.symbol, r.market);
                        const mktTag = r.market || parsed.market;
                        const colors = MARKET_COLORS[mktTag] || MARKET_COLORS.US;
                        return (
                            <button
                                key={r.symbol}
                                onClick={() => handleSelect(r.symbol)}
                                className="w-full flex items-center justify-between px-3 py-2 text-left transition-colors hover:bg-[var(--color-hover)]"
                            >
                                <div className="flex-1 min-w-0">
                                    <div className="text-[11px] font-semibold" style={{ color: 'var(--color-text)' }}>{parsed.display}</div>
                                    <div className="text-[10px] truncate" style={{ color: 'var(--color-text-sub)', maxWidth: 120 }}>
                                        {r.name_th || r.name}
                                    </div>
                                </div>
                                <span
                                    className="badge text-[9px] ml-2 flex-shrink-0"
                                    style={{ background: colors.bg, color: colors.text }}
                                >
                                    {mktTag}
                                </span>
                            </button>
                        );
                    })}
                </div>
            )}
        </div>
    );
}
