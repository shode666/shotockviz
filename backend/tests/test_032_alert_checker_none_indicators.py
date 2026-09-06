"""bd:shotockviz-032 — alert_checker must never compare a None indicator.

bd:shotockviz-kmi changed `compute_rsi` (was 50.0) and `compute_volume_ratio`
(was a vol_avg=1 fallback) to return None on insufficient data. Three of
alert_checker's five indicator branches then compared that result directly:
`rsi > alert.value` and `ratio >= alert.value` raise TypeError against None.

`_MIN_BARS_FOR_INDICATORS` (26) currently keeps this unreachable, but that
constant lives in a different file from the indicators' own minimums and
neither knows about the other, so the guard is what makes the invariant true
rather than coincidental.
"""
from types import SimpleNamespace

import pytest

from workers import alert_checker


class _Type:
    def __init__(self, value):
        self.value = value


def _alert(alert_type: str, value: float):
    return SimpleNamespace(alert_type=_Type(alert_type), value=value)


def _bars(n: int, close: float = 100.0, volume: float = 1_000_000.0):
    return [{"close": close + i, "volume": volume} for i in range(n)]


@pytest.mark.parametrize("alert_type,threshold", [
    ("RSI_OVERBOUGHT", 70.0),
    ("RSI_OVERSOLD", 30.0),
])
def test_rsi_types_do_not_raise_and_do_not_trigger_when_rsi_is_uncomputable(alert_type, threshold):
    """14 bars is below RSI(14)'s own minimum of period + 1 = 15."""
    from services import indicators
    closes = [b["close"] for b in _bars(14)]
    assert indicators.compute_rsi(closes) is None  # premise

    triggered, display = alert_checker._evaluate_indicator_alert(
        _alert(alert_type, threshold), _bars(14)
    )
    assert triggered is False
    assert display == 0.0


def test_volume_spike_does_not_raise_and_does_not_trigger_when_ratio_is_uncomputable():
    """19 bars is below compute_volume_ratio's lookback of 20."""
    from services import indicators
    volumes = [b["volume"] for b in _bars(19)]
    assert indicators.compute_volume_ratio(volumes) is None  # premise

    triggered, display = alert_checker._evaluate_indicator_alert(
        _alert("VOLUME_SPIKE", 3.0), _bars(19)
    )
    assert triggered is False
    assert display == 0.0


def test_uncomputable_is_not_silently_treated_as_a_trigger():
    """The failure mode this replaces was the opposite of a crash: the old
    sentinels (RSI 50.0, vol_avg 1) returned numbers that COMPARED, so a
    VOLUME_SPIKE alert fired on the raw share count every single time. Assert
    the direction explicitly — 'cannot evaluate' must mean no notification,
    not a notification."""
    triggered, _ = alert_checker._evaluate_indicator_alert(
        _alert("VOLUME_SPIKE", 1.5), _bars(19, volume=5_000_000.0)
    )
    assert triggered is False


@pytest.mark.parametrize("alert_type,threshold", [
    ("RSI_OVERBOUGHT", 70.0),
    ("RSI_OVERSOLD", 30.0),
    ("VOLUME_SPIKE", 3.0),
])
def test_enough_bars_still_evaluates_normally(alert_type, threshold):
    """The guard must not turn every indicator alert into a no-op."""
    from services import indicators
    bars = _bars(60)
    closes = [b["close"] for b in bars]
    assert indicators.compute_rsi(closes) is not None
    assert indicators.compute_volume_ratio([b["volume"] for b in bars]) is not None

    triggered, display = alert_checker._evaluate_indicator_alert(
        _alert(alert_type, threshold), bars
    )
    assert isinstance(triggered, bool)
    assert display != 0.0
