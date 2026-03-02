/**
 * Format a number as price with commas and decimals.
 */
export function formatPrice(value, decimals = 2) {
    if (value == null || isNaN(value)) return '—';
    return Number(value).toLocaleString('en-US', {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
    });
}

/**
 * Format a percentage value with + sign.
 */
export function formatPct(value, decimals = 2) {
    if (value == null || isNaN(value)) return '—';
    const num = Number(value);
    const sign = num >= 0 ? '+' : '';
    return `${sign}${num.toFixed(decimals)}%`;
}

/**
 * Format a change value with + sign.
 */
export function formatChange(value, decimals = 2) {
    if (value == null || isNaN(value)) return '—';
    const num = Number(value);
    const sign = num >= 0 ? '+' : '';
    return `${sign}${num.toFixed(decimals)}`;
}

/**
 * Format volume (e.g., 1500000 → "1.5M").
 */
export function formatVolume(value) {
    if (value == null || isNaN(value)) return '—';
    const num = Number(value);
    if (num >= 1e9) return `${(num / 1e9).toFixed(1)}B`;
    if (num >= 1e6) return `${(num / 1e6).toFixed(1)}M`;
    if (num >= 1e3) return `${(num / 1e3).toFixed(1)}K`;
    return num.toLocaleString();
}

/**
 * Format market cap (e.g., 450000000000 → "450B").
 */
export function formatMarketCap(value) {
    if (value == null || isNaN(value)) return '—';
    const num = Number(value);
    if (num >= 1e12) return `${(num / 1e12).toFixed(1)}T`;
    if (num >= 1e9) return `${(num / 1e9).toFixed(0)}B`;
    if (num >= 1e6) return `${(num / 1e6).toFixed(0)}M`;
    return num.toLocaleString();
}

/**
 * Relative time label (e.g., "10 นาทีที่แล้ว").
 */
export function timeAgo(dateStr) {
    if (!dateStr) return '';
    const diff = Date.now() - new Date(dateStr).getTime();
    const min = Math.floor(diff / 60000);
    if (min < 1) return 'เมื่อสักครู่';
    if (min < 60) return `${min} นาทีที่แล้ว`;
    const hr = Math.floor(min / 60);
    if (hr < 24) return `${hr} ชม.ที่แล้ว`;
    const d = Math.floor(hr / 24);
    return `${d} วันที่แล้ว`;
}
