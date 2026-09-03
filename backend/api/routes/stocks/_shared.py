"""Shared helpers for the stocks router package.

bd:deps-2026-09 WP-B5 — extracted verbatim from the pre-split
`backend/api/routes/stocks.py:22-31` (03-stan-refactor-strategy.md §2.1).
Pure file move, zero behavior change.
"""
import re

VALID_TIMEFRAMES = {"1m", "5m", "15m", "1h", "4h", "1D", "1W", "1M"}

# Yahoo Finance only accepts simple ticker symbols (letters, digits, dots, hyphens, carets).
# Thai mutual fund names like "SCBS&P500", "PRINCIPAL IPROP-D", "MPDIVMF" that contain
# spaces or & will never resolve — skip them to avoid 20s timeout per symbol.
_YAHOO_SYMBOL_RE = re.compile(r'^[\^]?[A-Z0-9]{1,10}([.\-][A-Z0-9]{1,4})?$')


def _is_yahoo_fetchable(symbol: str) -> bool:
    """Return True if the symbol looks like a real Yahoo Finance ticker."""
    return bool(_YAHOO_SYMBOL_RE.match(symbol.upper()))
