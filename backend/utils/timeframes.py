"""
Timeframe validation and normalization utilities.

Canonical timeframe strings used throughout the backend:
    1m  5m  15m  1h  4h  1D  1W  1M

Aliases (user-facing inputs that get normalized):
    1min → 1m
    1hour → 1h
    daily / day / d → 1D
    weekly / week / w → 1W
    monthly / month / mo → 1M
"""

from __future__ import annotations

from fastapi import HTTPException


# ── Canonical set ─────────────────────────────────────────────────────────────

#: All supported timeframe strings (ordered intraday → long-term).
VALID_TIMEFRAMES: tuple[str, ...] = ("1m", "5m", "15m", "1h", "4h", "1D", "1W", "1M")

#: Default timeframe used when the caller omits the parameter.
DEFAULT_TIMEFRAME: str = "1D"

# ── Alias table ───────────────────────────────────────────────────────────────

_ALIASES: dict[str, str] = {
    # Lowercase originals already canonical
    "1m":      "1m",
    "5m":      "5m",
    "15m":     "15m",
    "1h":      "1h",
    "4h":      "4h",
    "1d":      "1D",
    "1w":      "1W",
    "1mo":     "1M",
    # Common user-facing aliases
    "1min":    "1m",
    "5min":    "5m",
    "15min":   "15m",
    "1hour":   "1h",
    "4hour":   "4h",
    "daily":   "1D",
    "day":     "1D",
    "d":       "1D",
    "weekly":  "1W",
    "week":    "1W",
    "w":       "1W",
    "monthly": "1M",
    "month":   "1M",
    "mo":      "1M",
    # Uppercase canonical (pass-through)
    "1D":      "1D",
    "1W":      "1W",
    "1M":      "1M",
    "1H":      "1h",
    "4H":      "4h",
}


# ── Public helpers ────────────────────────────────────────────────────────────

def normalize(tf: str) -> str | None:
    """
    Convert ``tf`` to a canonical timeframe string, or return ``None`` if
    the input is not recognised.

    Does NOT raise — callers that want an error should use :func:`validate`.
    """
    return _ALIASES.get(tf.strip())


def validate(tf: str) -> str:
    """
    Return the canonical timeframe string for ``tf``.

    Raises :class:`fastapi.HTTPException` (422) with a descriptive message
    if ``tf`` is not recognised, so it can be used directly as a FastAPI
    dependency or called from route handlers.
    """
    canonical = normalize(tf)
    if canonical is None:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Invalid timeframe '{tf}'. "
                f"Supported values: {', '.join(VALID_TIMEFRAMES)}"
            ),
        )
    return canonical


def is_valid(tf: str) -> bool:
    """Return True if ``tf`` is a recognised timeframe (after normalization)."""
    return normalize(tf) is not None
