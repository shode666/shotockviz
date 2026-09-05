// bd:ui-honesty-2026-09 F9 — Export CSV (ScreenerPage.tsx:133), pure Blob
// download, no backend call. Columns match visible result table.

export interface ScreenerRow {
    sym: string;
    name: string;
    price: number | string;
    chg: number | string;
    rsi: number | string;
    macd: string;
    vol: string | number;
    signal: string;
}

const HEADERS = ['Symbol', 'ชื่อบริษัท', 'ราคา', 'เปลี่ยนแปลง', 'RSI', 'MACD', 'Volume', 'Signal'];

// Excel/Sheets treats a cell starting with one of these as a formula. A pure
// numeric-looking string (e.g. "-1", "+1.5%") is not a formula-injection
// vector — it's a completely ordinary negative/percentage value (chg, pct)
// and must round-trip unescaped.
const NUMERIC_LIKE = /^[+-]?\d+(\.\d+)?%?$/;

// Escape a single CSV field: wrap in quotes if it contains comma, quote, or newline;
// double any internal quotes (RFC 4180). Also neutralize formula-injection
// vectors (=, +, -, @, tab, CR) by prefixing a leading single quote before
// the RFC 4180 quoting runs, so Excel/Sheets won't execute the cell as a
// formula on open — but only for values that aren't plain numeric data
// (bd:ui-honesty-2026-09 Chris Medium #2; numeric exemption: negative chg/pct
// values like -1 or +1.5% must not be corrupted by the guard).
function escapeCsvField(value: unknown): string {
    let str = value === null || value === undefined ? '' : String(value);
    const isNumericLike = typeof value === 'number' || NUMERIC_LIKE.test(str);
    if (!isNumericLike && /^[=+\-@\t\r]/.test(str)) {
        str = `'${str}`;
    }
    if (/[",\n]/.test(str)) {
        return `"${str.replace(/"/g, '""')}"`;
    }
    return str;
}

export function resultsToCsv(results: ScreenerRow[]): string {
    const lines = [HEADERS.map(escapeCsvField).join(',')];
    for (const r of results) {
        lines.push([
            r.sym, r.name, r.price, r.chg, r.rsi, r.macd, r.vol, r.signal,
        ].map(escapeCsvField).join(','));
    }
    return lines.join('\r\n');
}
