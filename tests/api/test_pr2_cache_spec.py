"""
PR#2 acceptance tests — cache_keys + ttl_policy + timeframe validation.

DoD:
  ✓ Key formats correct for every endpoint type
  ✓ Lock key is always "lock:" + data key
  ✓ TTL defined for every canonical timeframe
  ✓ validate() returns canonical string for known aliases
  ✓ validate() raises 422 for unknown timeframe
  ✓ is_intraday() classifies correctly
"""
import pytest
from fastapi import HTTPException

import core.cache_keys as ck
from core.ttl_policy import (
    OHLCV_TTL,
    QUOTE_TTL,
    FUNDAMENTALS_TTL,
    SEARCH_TTL,
    FUND_NAV_TTL,
    SCREENER_SNAPSHOT_TTL,
    LOCK_TTL,
    ohlcv_ttl,
    is_intraday,
)
from utils.timeframes import (
    VALID_TIMEFRAMES,
    DEFAULT_TIMEFRAME,
    normalize,
    validate,
    is_valid,
)


# ══════════════════════════════════════════════════════════════════
# cache_keys
# ══════════════════════════════════════════════════════════════════

class TestCacheKeys:
    def test_quote_key(self):
        assert ck.quote("PTT.BK") == "quote:PTT.BK"

    def test_quote_key_us(self):
        assert ck.quote("AAPL") == "quote:AAPL"

    def test_ohlcv_key(self):
        assert ck.ohlcv("PTT.BK", "1D") == "ohlcv:PTT.BK:1D"

    def test_ohlcv_key_index(self):
        assert ck.ohlcv("^GSPC", "1W") == "ohlcv:^GSPC:1W"

    def test_ohlcv_key_fund_with_space(self):
        # Symbols with spaces/special chars must be preserved
        key = ck.ohlcv("PRINCIPAL iPROP-D", "1D")
        assert key == "ohlcv:PRINCIPAL iPROP-D:1D"

    def test_fundamentals_key(self):
        assert ck.fundamentals("TSLA") == "fundamentals:TSLA"

    def test_search_key_lowercased(self):
        assert ck.search("PTT") == "search:ptt"
        assert ck.search("  Apple  ") == "search:apple"

    def test_fund_key(self):
        assert ck.fund("SCBS&P500") == "fund:SCBS&P500"

    def test_screener_key(self):
        assert ck.screener("abc123") == "screener:abc123"

    def test_lock_wraps_data_key(self):
        data_key = ck.ohlcv("AAPL", "1h")
        assert ck.lock(data_key) == f"lock:{data_key}"

    def test_lock_quote(self):
        assert ck.lock(ck.quote("NVDA")) == "lock:quote:NVDA"

    def test_lock_screener(self):
        assert ck.lock(ck.screener("deadbeef")) == "lock:screener:deadbeef"

    def test_all_key_types_are_strings(self):
        for key_fn, args in [
            (ck.quote,         ("X",)),
            (ck.ohlcv,        ("X", "1D")),
            (ck.fundamentals,  ("X",)),
            (ck.search,        ("x",)),
            (ck.fund,          ("X",)),
            (ck.screener,      ("hash",)),
            (ck.lock,          ("any:key",)),
        ]:
            result = key_fn(*args)
            assert isinstance(result, str), f"{key_fn.__name__} returned non-str"


# ══════════════════════════════════════════════════════════════════
# ttl_policy
# ══════════════════════════════════════════════════════════════════

class TestTTLPolicy:
    def test_every_valid_timeframe_has_ttl(self):
        for tf in VALID_TIMEFRAMES:
            assert tf in OHLCV_TTL, f"Missing TTL for timeframe '{tf}'"

    def test_intraday_ttl_is_60s(self):
        for tf in ("1m", "5m", "15m"):
            assert OHLCV_TTL[tf] == 60

    def test_1h_4h_ttl_is_1h(self):
        assert OHLCV_TTL["1h"] == 3_600
        assert OHLCV_TTL["4h"] == 3_600

    def test_1d_ttl_is_6h(self):
        assert OHLCV_TTL["1D"] == 21_600

    def test_1w_1m_ttl_is_24h(self):
        assert OHLCV_TTL["1W"] == 86_400
        assert OHLCV_TTL["1M"] == 86_400

    def test_ohlcv_ttl_helper(self):
        assert ohlcv_ttl("1D") == 21_600
        assert ohlcv_ttl("1m") == 60

    def test_ohlcv_ttl_unknown_raises(self):
        with pytest.raises(KeyError):
            ohlcv_ttl("99X")

    def test_is_intraday_true(self):
        for tf in ("1m", "5m", "15m", "1h", "4h"):
            assert is_intraday(tf), f"Expected '{tf}' to be intraday"

    def test_is_intraday_false(self):
        for tf in ("1D", "1W", "1M"):
            assert not is_intraday(tf), f"Expected '{tf}' to NOT be intraday"

    def test_quote_ttl(self):
        assert QUOTE_TTL == 60

    def test_fundamentals_ttl(self):
        assert FUNDAMENTALS_TTL == 300

    def test_search_ttl(self):
        assert SEARCH_TTL == 86_400

    def test_fund_nav_ttl(self):
        assert FUND_NAV_TTL == 86_400

    def test_screener_ttl(self):
        assert SCREENER_SNAPSHOT_TTL == 300

    def test_lock_ttl_short(self):
        # Lock must expire quickly so crashed workers don't block forever
        assert LOCK_TTL <= 30

    def test_ttl_values_positive(self):
        for name, val in [
            ("QUOTE_TTL", QUOTE_TTL),
            ("FUNDAMENTALS_TTL", FUNDAMENTALS_TTL),
            ("SEARCH_TTL", SEARCH_TTL),
            ("FUND_NAV_TTL", FUND_NAV_TTL),
            ("SCREENER_SNAPSHOT_TTL", SCREENER_SNAPSHOT_TTL),
            ("LOCK_TTL", LOCK_TTL),
        ]:
            assert val > 0, f"{name} must be positive"


# ══════════════════════════════════════════════════════════════════
# timeframes — normalize / validate / is_valid
# ══════════════════════════════════════════════════════════════════

class TestTimeframeNormalize:
    """normalize() returns canonical string or None (never raises)."""

    @pytest.mark.parametrize("inp,expected", [
        # Canonical pass-through
        ("1m",   "1m"),
        ("5m",   "5m"),
        ("15m",  "15m"),
        ("1h",   "1h"),
        ("4h",   "4h"),
        ("1D",   "1D"),
        ("1W",   "1W"),
        ("1M",   "1M"),
        # Lowercase daily/weekly/monthly
        ("1d",   "1D"),
        ("1w",   "1W"),
        ("1mo",  "1M"),
        # Human aliases
        ("1min",    "1m"),
        ("5min",    "5m"),
        ("15min",   "15m"),
        ("1hour",   "1h"),
        ("4hour",   "4h"),
        ("daily",   "1D"),
        ("day",     "1D"),
        ("d",       "1D"),
        ("weekly",  "1W"),
        ("week",    "1W"),
        ("w",       "1W"),
        ("monthly", "1M"),
        ("month",   "1M"),
        ("mo",      "1M"),
        # Uppercase H
        ("1H",   "1h"),
        ("4H",   "4h"),
    ])
    def test_normalize(self, inp, expected):
        assert normalize(inp) == expected, f"normalize({inp!r}) should be {expected!r}"

    def test_unknown_returns_none(self):
        assert normalize("99X") is None
        assert normalize("") is None
        assert normalize("2D") is None
        assert normalize("30m") is None


class TestTimeframeValidate:
    """validate() returns canonical string or raises 422."""

    def test_valid_returns_canonical(self):
        assert validate("1D") == "1D"
        assert validate("daily") == "1D"
        assert validate("1min") == "1m"

    def test_invalid_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            validate("99X")
        assert exc_info.value.status_code == 422

    def test_error_message_contains_input(self):
        with pytest.raises(HTTPException) as exc_info:
            validate("BADTF")
        assert "BADTF" in exc_info.value.detail

    def test_error_message_lists_valid(self):
        with pytest.raises(HTTPException) as exc_info:
            validate("oops")
        # Should mention valid timeframes
        assert "1D" in exc_info.value.detail or "Supported" in exc_info.value.detail

    def test_empty_string_raises(self):
        with pytest.raises(HTTPException):
            validate("")


class TestTimeframeIsValid:
    def test_known_returns_true(self):
        for tf in VALID_TIMEFRAMES:
            assert is_valid(tf)

    def test_aliases_return_true(self):
        for alias in ("1min", "daily", "weekly", "monthly", "d", "w", "mo"):
            assert is_valid(alias), f"Expected '{alias}' to be valid"

    def test_unknown_returns_false(self):
        assert not is_valid("99X")
        assert not is_valid("2D")
        assert not is_valid("")


class TestDefaultTimeframe:
    def test_default_is_1d(self):
        assert DEFAULT_TIMEFRAME == "1D"

    def test_default_is_valid(self):
        assert is_valid(DEFAULT_TIMEFRAME)
