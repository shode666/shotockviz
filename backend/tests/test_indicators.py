"""Unit tests for services/indicators.py — the shared indicator module
extracted from api/routes/screener.py (bd:shotockviz-06e) so
workers/alert_checker.py reuses the exact same math instead of writing a
second, independently-drifting copy.

RSI/MACD/SMA already have full coverage in test_screener_indicators.py
(which imports them by name from api.routes.screener, unchanged by the
extraction). This file adds:
  (a) an identity check that screener's re-exported names ARE these
      functions, not incidental lookalikes — the actual anti-drift
      guarantee the extraction exists to provide;
  (b) coverage for compute_volume_ratio, the one function screener never
      exposed a standalone name for before this ticket.

bd:shotockviz-kmi (2026-09-06) — the insufficient-data cases below were
updated: compute_volume_ratio now returns None instead of the
raw-volume-as-ratio sentinel this file used to explicitly document and
preserve (see git history for the removed
"denominator quirk preserved from screener" test). See
test_kmi_indicators.py for the full RED-proof and the caller-side
(screener._evaluate_symbol) coverage this ticket also added.
"""
import services.indicators as indicators
from api.routes import screener


class TestSameFunctionObject:
    """The whole point of the extraction: screener and alert_checker call
    the literal same function object, not two implementations that
    happen to agree today and can silently drift apart tomorrow."""

    def test_screener_rsi_is_shared_indicators_rsi(self):
        assert screener._compute_rsi is indicators.compute_rsi

    def test_screener_macd_is_shared_indicators_macd(self):
        assert screener._compute_macd is indicators.compute_macd

    def test_screener_sma_is_shared_indicators_sma(self):
        assert screener._compute_sma is indicators.compute_sma

    def test_screener_volume_ratio_is_shared_indicators_volume_ratio(self):
        assert screener._compute_volume_ratio is indicators.compute_volume_ratio


class TestComputeVolumeRatio:
    def test_empty_list_returns_none(self):
        # bd:shotockviz-kmi — was 0.0 (a value that IS "no spike", so this
        # particular case never false-positived a filter, but was still a
        # fabricated number rather than "cannot compute"). Now None.
        assert indicators.compute_volume_ratio([]) is None

    def test_no_spike_ratio_around_one(self):
        volumes = [100.0] * 25
        assert indicators.compute_volume_ratio(volumes) == 1.0

    def test_spike_ratio_uses_20_bar_lookback_window(self):
        # 30 bars: first 29 at 100, latest bar spikes to 400.
        # lookback=20 window = the last 20 bars = 19x100 + 1x400.
        volumes = [100.0] * 29 + [400.0]
        avg = (19 * 100.0 + 400.0) / 20
        assert indicators.compute_volume_ratio(volumes) == 400.0 / avg

    def test_insufficient_history_returns_none_not_raw_volume(self):
        # bd:shotockviz-kmi — this used to be BIT-FOR-BIT PRESERVED from
        # the original screener inline calc
        # (`vol_avg20 = ... if len(volumes) >= 20 else 1`): below the
        # lookback window, the denominator was the literal integer 1, so
        # the "ratio" was just the raw current volume — millions for any
        # real symbol, satisfying both the screener's "> 2x Average" and
        # "> 1.5x Average" filters every time. Dead code in practice both
        # callers (screener, alert_checker) already require >= 26 bars
        # before this is ever invoked, per test_kmi_indicators.py's
        # caller-side coverage — but "kept as-is, out of scope" was
        # exactly the reasoning bd:shotockviz-kmi's filing exists to
        # overturn: an unrelated length check elsewhere is not a
        # substitute for the function itself saying "cannot compute".
        assert indicators.compute_volume_ratio([50.0, 50.0, 100.0], lookback=20) is None
