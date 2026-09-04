/**
 * Format a number as price with commas and decimals (US locale).
 */
export function formatPrice(value: number | string | null | undefined, decimals = 2): string {
    if (value == null || isNaN(value as number)) return '—';
    return Number(value).toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    });
}

/**
 * Format a number as price with Thai locale.
 */
export function formatPriceTH(value: number | string | null | undefined, decimals = 2): string {
    if (value == null || isNaN(value as number)) return '—';
    return Number(value).toLocaleString('th-TH', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    });
}

/**
 * Format a percentage value with + sign.
 */
export function formatPct(value: number | string | null | undefined, decimals = 2): string {
    if (value == null || isNaN(value as number)) return '—';
    const num = Number(value);
    const sign = num >= 0 ? '+' : '';
    return `${sign}${num.toFixed(decimals)}%`;
}

/**
 * Format a change value with + sign.
 */
export function formatChange(value: number | string | null | undefined, decimals = 2): string {
    if (value == null || isNaN(value as number)) return '—';
    const num = Number(value);
    const sign = num >= 0 ? '+' : '';
    return `${sign}${num.toFixed(decimals)}`;
}

/**
 * Format volume (e.g., 1500000 → "1.5M").
 */
export function formatVolume(value: number | string | null | undefined): string {
    if (value == null || isNaN(value as number)) return '—';
    const num = Number(value);
    if (num >= 1e9) return `${(num / 1e9).toFixed(1)}B`;
    if (num >= 1e6) return `${(num / 1e6).toFixed(1)}M`;
    if (num >= 1e3) return `${(num / 1e3).toFixed(1)}K`;
    return num.toLocaleString();
}

/**
 * Format market cap (e.g., 450000000000 → "450B").
 */
export function formatMarketCap(value: number | string | null | undefined): string {
    if (value == null || isNaN(value as number)) return '—';
    const num = Number(value);
    if (num >= 1e12) return `${(num / 1e12).toFixed(1)}T`;
    if (num >= 1e9) return `${(num / 1e9).toFixed(0)}B`;
    if (num >= 1e6) return `${(num / 1e6).toFixed(0)}M`;
    return num.toLocaleString();
}

/**
 * Yahoo Finance suffix → market tag mapping.
 * Internal symbol keeps suffix for API calls,
 * but display strips it and shows market tag instead.
 */
const SUFFIX_MARKET_MAP: Record<string, string> = {
    '.BK': 'SET',    // Thailand SET/MAI
    '.T':  'JP',     // Tokyo Stock Exchange
    '.SS': 'CN',     // Shanghai Stock Exchange
    '.SZ': 'CN',     // Shenzhen Stock Exchange
    '.HK': 'HK',     // Hong Kong Stock Exchange
    '.L':  'UK',     // London Stock Exchange
    '.DE': 'DE',     // XETRA / Frankfurt
    '.PA': 'FR',     // Euronext Paris
    '.AS': 'NL',     // Euronext Amsterdam
    '.MI': 'IT',     // Borsa Italiana
    '.TO': 'CA',     // Toronto Stock Exchange
    '.AX': 'AU',     // Australian Securities Exchange
    '.KS': 'KR',     // Korea Exchange
    '.TW': 'TW',     // Taiwan Stock Exchange
    '.SI': 'SG',     // Singapore Exchange
};

export interface ParsedSymbol {
    display: string;
    market: string;
    suffix: string;
}

/**
 * Strip exchange suffix from symbol for display.
 * Returns { display, market, suffix }
 *
 * Example:
 *   parseSymbol('ADVANC.BK')  → { display: 'ADVANC', market: 'SET', suffix: '.BK' }
 *   parseSymbol('7203.T')     → { display: '7203',   market: 'JP',  suffix: '.T' }
 *   parseSymbol('AAPL')       → { display: 'AAPL',   market: 'US',  suffix: '' }
 *   parseSymbol('SCBS&P500')  → { display: 'SCBS&P500', market: 'FUND', suffix: '' }
 */
export function parseSymbol(symbol: string | null | undefined, marketHint?: string): ParsedSymbol {
    if (!symbol) return { display: '—', market: '', suffix: '' };

    for (const [suffix, market] of Object.entries(SUFFIX_MARKET_MAP)) {
        if (symbol.endsWith(suffix)) {
            return {
                display: symbol.slice(0, -suffix.length),
                market,
                suffix,
            };
        }
    }

    // No suffix — use marketHint if available
    return {
        display: symbol,
        market: marketHint || (symbol.includes('&') || symbol.includes(' ') ? 'FUND' : 'US'),
        suffix: '',
    };
}

/**
 * Get just the display symbol (no suffix).
 * Shorthand for parseSymbol(sym).display
 */
export function displaySymbol(symbol: string | null | undefined): string {
    return parseSymbol(symbol).display;
}

/**
 * Market tag color config for badges.
 */
export const MARKET_COLORS: Record<string, { bg: string; text: string }> = {
    // US text was #7c5cfc (3.59:1 on the badge composite over --color-panel #12141d
    // — fails AA) — bd:ux-2026-09 Uma final check. #9d85ff measures 4.80:1 on the
    // surface-3-over-bg composite (same violet as --color-accent-text-strong).
    US:   { bg: 'rgba(157,133,255,0.15)', text: '#9d85ff' },
    SET:  { bg: 'rgba(52,211,153,0.15)',   text: '#34d399' },
    FUND: { bg: 'rgba(251,191,36,0.15)',   text: '#fbbf24' },
    JP:   { bg: 'rgba(248,113,113,0.15)',  text: '#f87171' },
    CN:   { bg: 'rgba(251,146,60,0.15)',   text: '#fb923c' },
    HK:   { bg: 'rgba(251,146,60,0.15)',   text: '#fb923c' },
    UK:   { bg: 'rgba(96,165,250,0.15)',   text: '#60a5fa' },
    DE:   { bg: 'rgba(96,165,250,0.15)',   text: '#60a5fa' },
    FR:   { bg: 'rgba(96,165,250,0.15)',   text: '#60a5fa' },
    KR:   { bg: 'rgba(248,113,113,0.15)',  text: '#f87171' },
};

/**
 * Market → currency mapping for display.
 */
export const MARKET_CURRENCY: Record<string, { sign: string; code: string }> = {
    US:   { sign: '$',  code: 'USD' },
    SET:  { sign: '฿',  code: 'THB' },
    FUND: { sign: '฿',  code: 'THB' },
    JP:   { sign: '¥',  code: 'JPY' },
    CN:   { sign: '¥',  code: 'CNY' },
    HK:   { sign: 'HK$', code: 'HKD' },
    UK:   { sign: '£',  code: 'GBP' },
    DE:   { sign: '€',  code: 'EUR' },
    FR:   { sign: '€',  code: 'EUR' },
    KR:   { sign: '₩',  code: 'KRW' },
};

/**
 * Relative time label (e.g., "10 นาทีที่แล้ว").
 * Returns Thai-language relative time strings.
 */
export function timeAgo(dateStr: string | null | undefined): string {
    if (!dateStr) return '';
    const diff = Date.now() - new Date(dateStr).getTime();
    if (isNaN(diff)) return '';
    const mins = Math.floor(diff / 60000);
    if (mins < 1) return 'เพิ่งเผยแพร่';
    if (mins < 60) return `${mins} นาทีที่แล้ว`;
    const hrs = Math.floor(mins / 60);
    if (hrs < 24) return `${hrs} ชม.ที่แล้ว`;
    return `${Math.floor(hrs / 24)} วันที่แล้ว`;
}

/**
 * Get color for up/down values (green for positive, red for negative).
 * Returns CSS color variable or default neutral gray.
 */
export function upColor(value: number | null | undefined): string {
    if (value == null) return 'var(--color-text-sub)';
    return value >= 0 ? 'var(--color-green)' : 'var(--color-red)';
}
