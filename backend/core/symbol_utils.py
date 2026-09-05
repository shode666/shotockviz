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


# ── Thai fund-house prefixes (classification signal, NOT ambiguity) ──────────
# Known Thai fund-house (บลจ.) prefixes used purely as a *fund-code shape*
# heuristic — see `symbol_registrar._classify_market`, which uses this list
# to guess that an unknown bare symbol (e.g. "TISCOGF", "SCBLT1", "KFLTFDIV")
# is a Thai mutual fund code, not a SET equity. This is a *different
# question* from "is this bare symbol ambiguous with a real ticker" (that
# question is answered by `THAI_FUND_HOUSE_TICKER_COLLISIONS` /
# `is_ambiguous_bare_thai_symbol` below) — the two must not be collapsed
# into one constant again (bd:shotockviz-3p6 fixed exactly that overload:
# `startswith` on this whole list was being used as the ambiguity check,
# which flags every genuine fund code — TISCOGF, SCBLT1, KFLTFDIV, K-CHINA,
# B-INNOTECH — as if it were an unresolvable stock/fund collision, when none
# of those strings are also SET tickers).
THAI_FUND_PREFIXES: tuple[str, ...] = (
    "SCB", "SCBS", "PRINCIPAL", "KFIN", "KF", "KTAM", "KT-", "K-",
    "B-", "BBLAM", "TISCO", "TMB", "UOBAM", "ONE-", "ASP", "PHATRA",
    "MFC", "LHFUND", "KRUNGSRI", "WE-", "MEGA", "DAOL",
)

# ── Thai fund-house / SET-ticker exact collisions (bd:shotockviz-3p6) ────────
# Ambiguity is real only when the *entire bare symbol* is simultaneously a
# genuine SET-listed ticker AND a fund-house name — not merely a prefix of
# one. Prefix fragments like "K-", "B-", "WE-", "ONE-", "KT-" are never
# whole tickers by construction (SET tickers don't contain "-" as their
# first/only token per `seed_stocks.py`'s 15 hardcoded names), so they
# cannot collide with anything and must never appear here.
#
# NO MAGIC evidence — each candidate below was checked against live Yahoo
# Finance from inside the backend container on 2026-09-05
# (`docker-compose -f docker-compose.dev.yml exec -T backend python3 -c
# "import yfinance as yf; ..."`), querying both the bare symbol and the
# `.BK`-suffixed form:
#
#   SCB    -> SCB.BK resolves: shortName "SCB_SCB X", quoteType EQUITY,
#             exchange SET, regularMarketPrice 151.5 (real, live SET
#             equity — SCB X Public Company Limited). Bare "SCB" resolves
#             to Yahoo's own placeholder (shortName "1249", quoteType
#             MUTUALFUND, exchange "YHD", regularMarketPrice None) —
#             confirmed collision.
#   TISCO  -> TISCO.BK resolves: "TISCO Financial Group Public Company
#             Limited", quoteType EQUITY, exchange SET, price 127.0 (real).
#             Bare "TISCO" returns nothing from Yahoo at all — still a
#             genuine SET ticker per the suffixed lookup, so the bare form
#             is a real collision risk with TISCOGF/TISCOEGF fund codes
#             (`seed_stocks.py` THAI_FUNDS section) — confirmed collision.
#   ASP    -> ASP.BK resolves: "Asia Plus Group Holdings Public Company
#             Limited", quoteType EQUITY, exchange SET, price 2.34 (real).
#             Bare "ASP" returns the same kind of Yahoo MUTUALFUND
#             placeholder as bare SCB (shortName "4507") — confirmed
#             collision.
#   MFC    -> MFC.BK resolves: "MFC Asset Management Public Company
#             Limited", quoteType EQUITY, exchange SET, price 23.5 (real —
#             MFC is itself both the fund house AND a SET-listed company).
#             Bare "MFC" resolves to an unrelated real US stock (Manulife
#             Financial Corporation, exchange NYQ, price 44.34) — still a
#             genuine ambiguity: a bare "MFC" cannot be safely assumed to
#             mean the Thai company — confirmed collision.
#   TMB    -> TMB.BK returns no data at all (quoteType "NONE", every field
#             None) — TMB Bank merged into ttb (Thanachart) in 2021 and no
#             longer trades under this ticker on Yahoo. Not a live SET
#             ticker today -> EXCLUDED, left as a plain THAI_FUND_PREFIXES
#             entry only.
#   DAOL   -> DAOL.BK and bare "DAOL" both return no data at all -> not a
#             resolvable SET ticker via this project's only disambiguation
#             source -> EXCLUDED.
#   PHATRA -> PHATRA.BK and bare "PHATRA" both return no data at all ->
#             EXCLUDED, same reasoning as DAOL.
THAI_FUND_HOUSE_TICKER_COLLISIONS: frozenset[str] = frozenset({
    "SCB", "TISCO", "ASP", "MFC",
})


def is_ambiguous_bare_thai_symbol(symbol: str) -> bool:
    """True only if `symbol` (bare, no `.BK`/`.MAI` suffix) is *exactly* one
    of the small set of strings that are simultaneously a real SET-listed
    ticker and a Thai fund-house name (see
    `THAI_FUND_HOUSE_TICKER_COLLISIONS` for the verified list and how each
    entry was checked).

    A symbol that merely *starts with* a fund-house prefix (e.g. "TISCOGF",
    "SCBLT1", "KFLTFDIV") is not ambiguous — it is unmistakably a fund code,
    not a stock ticker typed without its suffix. That broader prefix check
    was the bd:shotockviz-3p6 bug: it flagged every genuine fund code as if
    it collided with a real ticker.

    Symbols already carrying the market suffix (e.g. "SCB.BK") are never
    ambiguous — the suffix is the app's accepted disambiguation signal.
    """
    sym_upper = symbol.upper()
    if is_thai_stock(sym_upper):
        return False
    return sym_upper in THAI_FUND_HOUSE_TICKER_COLLISIONS


def ambiguous_bare_symbol_detail(symbol: str) -> str:
    """The one wording for a refused bare symbol (bd:shotockviz-3p6).

    `watchlist.py` and `portfolio.py` both refuse these now. The message lives
    here so the two routes cannot drift into telling the user two different
    stories about the same symbol — which is the shape of the bug 3p6 reports
    (the watchlist explained itself; the portfolio said nothing at all and the
    registrar silently declined behind it).
    """
    sym = symbol.upper()
    return (
        f"'{sym}' is ambiguous. For the SET stock, type '{sym}.BK'. "
        f"For a Thai mutual fund, use its exact fund code."
    )
