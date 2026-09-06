"""bd:shotockviz-kmi — compute_rsi / compute_volume_ratio must return None
on insufficient data, not a value that can pass as a real computation
(the same class of fix already applied to compute_sma under
bd:shotockviz-0x0).

RED-proof (see report for the exact command run): with this bd's source
change to services/indicators.py reverted (`git stash` the diff to
backend/services/indicators.py, backend/api/routes/screener.py), running
this file failed:
  - TestComputeRSIInsufficientData::test_returns_none_not_50
    -> AssertionError: assert 50.0 is None
  - TestComputeVolumeRatioInsufficientData::test_empty_list_returns_none_not_zero
    -> AssertionError: assert 0.0 is None
  - TestComputeVolumeRatioInsufficientData::test_returns_none_not_raw_volume_as_ratio
    -> AssertionError: assert 5000000.0 is None
  - TestScreenerExcludesWhenIndicatorUnavailable (both cases)
    -> AssertionError: assert {...} is None  (old screener code had no
       None-guard for rsi/vol_ratio at all, so a monkeypatched None
       propagated straight into `_matches_rsi`/`_compute_signal`/the
       result dict instead of excluding the symbol)
Restoring the stashed diff turned all of the above green.
"""
import pytest

import services.indicators as indicators
from api.routes import screener


class TestComputeRSIInsufficientData:
    def test_returns_none_not_50(self):
        closes = [100.0, 101.0, 102.0]  # 3 < period(14) + 1
        assert indicators.compute_rsi(closes, period=14) is None

    def test_returns_none_one_short_of_the_boundary(self):
        closes = [100.0] * 14  # exactly period(14), still needs period+1
        assert indicators.compute_rsi(closes, period=14) is None

    def test_computes_normally_once_enough_data(self):
        closes = [float(i) for i in range(100)]
        rsi = indicators.compute_rsi(closes, period=14)
        assert rsi is not None
        assert 0 <= rsi <= 100


class TestComputeVolumeRatioInsufficientData:
    def test_empty_list_returns_none_not_zero(self):
        assert indicators.compute_volume_ratio([]) is None

    def test_returns_none_not_raw_volume_as_ratio(self):
        # Old sentinel: vol_avg forced to the literal int 1 below the
        # lookback window, so the "ratio" degenerated to the raw current
        # volume — millions for any real symbol, which satisfied both the
        # screener's "> 2x Average" and "> 1.5x Average" filters every time.
        volumes = [50.0, 50.0, 5_000_000.0]  # 3 < lookback(20)
        assert indicators.compute_volume_ratio(volumes, lookback=20) is None

    def test_computes_normally_once_enough_data(self):
        volumes = [100.0] * 19 + [400.0]  # exactly lookback(20)
        ratio = indicators.compute_volume_ratio(volumes, lookback=20)
        assert ratio is not None
        assert ratio > 1.0


class _FakeBar:
    """Minimal stand-in for models.ohlcv.OHLCVBar — only the attributes
    screener._evaluate_symbol actually reads."""

    def __init__(self, symbol: str, close: float, volume: float):
        self.symbol = symbol
        self.close = close
        self.high = close
        self.low = close
        self.open = close
        self.volume = volume


def _bars(n: int = 30) -> list[_FakeBar]:
    return [_FakeBar("TEST", 100.0 + i, 1_000_000.0) for i in range(n)]


class TestScreenerExcludesWhenIndicatorUnavailable:
    """bd:shotockviz-kmi acceptance criteria: "callers handle the
    unavailable case explicitly, and a test fails if a sentinel is
    reintroduced." This exercises the caller
    (api.routes.screener._evaluate_symbol), not just the indicator
    functions in isolation.

    The real `len(bars) < 26` guard at the top of _evaluate_symbol makes
    rsi/vol_ratio ever being None unreachable today (RSI needs 15 closes,
    volume ratio needs 20 volumes, both < 26) — the exact same shape as
    the already-fixed MA200 case (bd:shotockviz-0x0), which WAS reachable
    only because 26 < 200. Monkeypatching the indicator functions to
    return None (something a future change to that 26-bar guard, or to
    the RSI/volume-ratio minimums, could make real) proves the caller
    excludes the symbol rather than crashing or silently passing a None
    through as if it were a real number.
    """

    def test_none_rsi_excludes_symbol(self, monkeypatch):
        monkeypatch.setattr(screener, "_compute_rsi", lambda closes: None)
        result = screener._evaluate_symbol(_bars(), "Test Co", "any", "any", "any", "any")
        assert result is None

    def test_none_volume_ratio_excludes_symbol(self, monkeypatch):
        monkeypatch.setattr(screener, "_compute_volume_ratio", lambda volumes: None)
        result = screener._evaluate_symbol(_bars(), "Test Co", "any", "any", "any", "any")
        assert result is None


class TestMatchesRSINeverPassesOnNone:
    def test_none_never_matches_oversold(self):
        assert screener._matches_rsi(None, "oversold") is False

    def test_none_never_matches_neutral(self):
        assert screener._matches_rsi(None, "neutral") is False

    def test_none_never_matches_overbought(self):
        assert screener._matches_rsi(None, "overbought") is False

    def test_none_still_passes_any_filter(self):
        # "any" doesn't test RSI at all — mirrors _matches_price's
        # ma200=None/flt="any" case (already covered in
        # test_screener_indicators.py::TestMatchesPrice).
        assert screener._matches_rsi(None, "any") is True


# bd:shotockviz-kmi — `TestAlertCheckerCallerGapNotFixedHere` lived here.
#
# It characterized the one caller this bead's file scope could not reach:
# `workers/alert_checker.py`'s RSI_OVERBOUGHT/RSI_OVERSOLD/VOLUME_SPIKE
# branches compared `compute_rsi`/`compute_volume_ratio`'s result directly
# with no None guard, and it asserted that they RAISE TypeError — a
# deliberately red-documented gap, with a note saying it should be removed
# together with the fix.
#
# That fix landed (bd:shotockviz-032, guard added
# in `_evaluate_indicator_alert`), so the class is gone rather than left
# asserting a bug that no longer exists. Its coverage moved, inverted, to
# `backend/tests/test_032_alert_checker_none_indicators.py`, which asserts the
# branches now return `(False, 0.0)` instead of raising — and which was
# red-proven against the pre-guard file with exactly the three TypeErrors this
# class used to expect.
