"""Shared symbol utilities: normalization, partitioning, market detection.

Eliminates duplication of YAHOO_MAP, suffix detection, and symbol
classification across price_fetcher, history_prefetcher, stock_service,
index_populator, and symbol_registrar.
"""
from __future__ import annotations


# ── Yahoo Finance symbol normalization ────────────────────────────────────────
# Some symbols use dots that Yahoo expects as dashes.
YAHOO_SYMBOL_MAP: dict[str, str] = {
    "BRK.B": "BRK-B",
    "BRK.A": "BRK-A",
    "BF.B": "BF-B",
    "BF.A": "BF-A",
}


def normalize_for_yahoo(symbol: str) -> str:
    """Convert internal symbol to Yahoo Finance compatible format."""
    return YAHOO_SYMBOL_MAP.get(symbol, symbol)


def denormalize_from_yahoo(yahoo_sym: str) -> str:
    """Convert Yahoo Finance symbol back to internal format."""
    reverse = {v: k for k, v in YAHOO_SYMBOL_MAP.items()}
    return reverse.get(yahoo_sym, yahoo_sym)


# ── Yahoo suffix → market tag mapping ─────────────────────────────────────────
SUFFIX_TO_MARKET: dict[str, str] = {
    ".BK": "SET",
    ".T": "JP",
    ".SS": "CN",
    ".SZ": "CN",
    ".HK": "HK",
    ".L": "UK",
    ".DE": "DE",
    ".PA": "FR",
    ".AS": "NL",
    ".MI": "IT",
    ".TO": "CA",
    ".AX": "AU",
    ".KS": "KR",
    ".TW": "TW",
    ".SI": "SG",
}

# Thai exchange identifiers from Yahoo search API
THAI_EXCHANGES: frozenset[str] = frozenset({"SET", "MAI", "BKK", "Bangkok"})


def detect_market(symbol: str) -> str:
    """Detect market from Yahoo Finance suffix.

    Args:
        symbol: Stock symbol (e.g., "7203.T", "PTT.BK", "AAPL")

    Returns:
        Market string (e.g., "JP", "SET", "US")
    """
    for suffix, market in SUFFIX_TO_MARKET.items():
        if symbol.endswith(suffix):
            return market
    return "US"


def is_thai_stock(symbol: str) -> bool:
    """Check if symbol is a Thai SET/MAI stock."""
    return symbol.endswith(".BK") or symbol.endswith(".MAI")


def is_fund(symbol: str) -> bool:
    """Heuristic: symbols with & or spaces are likely funds."""
    return "&" in symbol or " " in symbol


def partition_by_market(symbols: list[str]) -> tuple[list[str], list[str]]:
    """Split symbols into (thai, non_thai) buckets.

    Args:
        symbols: Mixed list of symbols.

    Returns:
        (thai_symbols, other_symbols) tuple. Both are deduplicated.
    """
    thai = []
    other = []
    seen = set()

    for s in symbols:
        if s in seen:
            continue
        seen.add(s)
        if is_thai_stock(s):
            thai.append(s)
        else:
            other.append(s)

    return thai, other


def deduplicate(symbols: list[str]) -> list[str]:
    """Remove duplicates while preserving order."""
    return list(dict.fromkeys(symbols))


# ── Crypto detection (bd:features-2026-09 slice B — Tara §2.3 allowlist) ─────
def is_crypto(symbol: str) -> bool:
    """BTC-USD / ETH-USD (intentional allowlist-by-suffix, not open regex).

    Safe vs BRK-B/BF-B (suffix "-B", not "-USD", see YAHOO_SYMBOL_MAP above)
    and internal dot-form BRK.B. THBUSD=X ends with "=X", not "-USD" → no clash.
    """
    return symbol.upper().endswith("-USD")


# ── Thai fund-prefix ambiguity (bd:shotockviz-m6q) ────────────────────────────
# Known Thai fund-house (บลจ.) prefixes. Several of these — SCB, TISCO, K-,
# B-, ASP — are simultaneously real SET equity tickers (Siam Commercial Bank,
# Tisco Financial Group, ...) and fund-code prefixes (SCBLT1, TISCOGF,
# K-GINCOME, B-INCOME, ...). The app's accepted convention is that SET
# tickers always carry an explicit ".BK" suffix; a bare symbol that merely
# *starts with* one of these prefixes cannot be told apart from the real
# stock without that suffix.
#
# NO MAGIC evidence for why this can't be resolved by guessing instead:
#   - No comprehensive local SET symbol list exists to check against —
#     `backend/scripts/seed_stocks.py` hardcodes 15 SET names only.
#   - Live yfinance lookup is not a reliable disambiguator either: bare
#     "SCB" resolves to Yahoo's own shortName "1249" / quoteType
#     MUTUALFUND / regularMarketPrice None (a generic Yahoo-Data
#     placeholder, not real SCB.BK or a real Thai fund) — same for "ASP" ->
#     "4507". Verified via `docker-compose exec backend python3 -c
#     "yfinance..."` on 2026-09-05; the data yfinance returns for a bare
#     ambiguous symbol is itself untrustworthy signal.
# Given both potential sources of truth are absent/unreliable, treat the
# bare form as ambiguous rather than silently picking a market.
THAI_FUND_PREFIXES: tuple[str, ...] = (
    "SCB", "SCBS", "PRINCIPAL", "KFIN", "KF", "KTAM", "KT-", "K-",
    "B-", "BBLAM", "TISCO", "TMB", "UOBAM", "ONE-", "ASP", "PHATRA",
    "MFC", "LHFUND", "KRUNGSRI", "WE-", "MEGA", "DAOL",
)


def is_ambiguous_bare_thai_symbol(symbol: str) -> bool:
    """True if `symbol` collides with a Thai fund-house prefix but carries
    no `.BK`/`.MAI` suffix to disambiguate it from a real SET equity.

    Symbols already carrying the market suffix (e.g. "SCB.BK") are never
    ambiguous — the suffix is the app's accepted disambiguation signal.
    """
    sym_upper = symbol.upper()
    if is_thai_stock(sym_upper):
        return False
    return any(sym_upper.startswith(prefix) for prefix in THAI_FUND_PREFIXES)
