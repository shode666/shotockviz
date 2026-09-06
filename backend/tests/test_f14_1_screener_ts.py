"""bd:shotockviz-f14.1 — "as-of is still missing on screener computed
columns and the news list", screener slice.

`_evaluate_symbol` computes RSI/MACD/MA/volume-ratio purely from the
`bars` list it is given. The honest as-of for those numbers is the date of
the newest bar actually used to compute them — NOT `time.time()` (the
request time) and NOT a cache TTL (screener reads OHLCV rows straight out
of PostgreSQL, `_fetch_symbol_bars`, no Redis TTL to infer from at all).
`_fetch_symbol_bars` orders bars ascending oldest->newest (see its own
"bd:shotockviz-p0y" comment) so `bars[-1]` is the same bar `closes[-1]` /
`close_now` inside `_evaluate_symbol` come from.

RED-proof (see Dave's hand-off report): before this bd's fix, the dict
returned by `_evaluate_symbol` had no "ts" key at all, so
`test_ts_is_the_newest_bars_own_time_unix` and
`test_ts_is_not_wall_clock_even_when_bars_are_stale` both failed on
`assert "ts" in result` — plain `AssertionError: False`, not a KeyError,
because there was nothing to look up yet.
"""
import time
from dataclasses import dataclass

import pytest

from api.routes.screener import _evaluate_symbol


@dataclass
class FakeBar:
    """Just enough of models.ohlcv.OHLCVBar for `_evaluate_symbol`: it only
    ever reads .symbol, .close, .volume, .time_unix off bar objects."""
    symbol: str
    close: float
    volume: float
    time_unix: int


def _make_bars(n: int, newest_time_unix: int, symbol: str = "NVDA") -> list[FakeBar]:
    """n bars, ascending oldest->newest (matches `_fetch_symbol_bars`'s
    real ordering contract), one simulated trading day (86400s) apart,
    with enough price/volume variation that RSI (needs 15 closes) and
    volume ratio (needs 20 volumes) are real numbers, not None."""
    bars = []
    for i in range(n):
        t = newest_time_unix - (n - 1 - i) * 86400
        close = 100.0 + (i % 5) - (i % 3)  # some up/down movement, never flat
        volume = 1_000_000.0 + (i * 1000)
        bars.append(FakeBar(symbol=symbol, close=close, volume=volume, time_unix=t))
    return bars


class TestScreenerRowTs:
    def test_ts_is_the_newest_bars_own_time_unix(self):
        """The row's `ts` must be the literal `time_unix` of the newest bar
        the indicators were computed from — the same bar `close_now` comes
        from (bars[-1]), not a fabricated or derived value."""
        newest = 1_700_000_000
        bars = _make_bars(30, newest_time_unix=newest)

        result = _evaluate_symbol(
            bars, name="NVIDIA", rsi_filter="any", volume_filter="any",
            macd_filter="any", price_filter="any",
        )

        assert result is not None
        assert "ts" in result
        assert result["ts"] == newest
        assert result["ts"] == bars[-1].time_unix

    def test_ts_is_not_wall_clock_even_when_bars_are_stale(self, monkeypatch):
        """Freeze `time.time()` far in the future relative to the bars'
        own dates and confirm `ts` still reports the bars' real (old) date
        — proving this is read from the data, not stamped at request time
        the way a naive `int(time.time())` in the response builder would."""
        very_old = 1_600_000_000  # bars' own newest date
        far_future_now = 1_900_000_000
        monkeypatch.setattr(time, "time", lambda: far_future_now)

        bars = _make_bars(30, newest_time_unix=very_old)
        result = _evaluate_symbol(
            bars, name="NVIDIA", rsi_filter="any", volume_filter="any",
            macd_filter="any", price_filter="any",
        )

        assert result is not None
        assert result["ts"] == very_old
        assert result["ts"] != far_future_now

    def test_ts_present_on_every_returned_row_never_none(self):
        """`_evaluate_symbol` only ever returns a dict when `bars` has
        >= 26 rows (guard at the top of the function) — so unlike
        fundamentals.py's TTL-derived ts, a returned screener row's ts is
        never None; there is no cache-miss/no-TTL case to fall into."""
        bars = _make_bars(40, newest_time_unix=1_650_000_000)
        result = _evaluate_symbol(
            bars, name="Test Co", rsi_filter="any", volume_filter="any",
            macd_filter="any", price_filter="any",
        )
        assert result is not None
        assert result["ts"] is not None
        assert isinstance(result["ts"], int)
