"""Unit tests for screener indicator computations — pure math, no I/O.

These functions live in api.routes.screener but are pure functions
that can be tested directly without any database or HTTP setup.
"""
import pytest
import math
import sys
import os

# Add backend to path for direct import
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from api.routes.screener import (
    _compute_rsi,
    _compute_macd,
    _compute_sma,
    _compute_signal,
    _matches_rsi,
    _matches_volume,
    _matches_macd,
    _matches_price,
)


# ── RSI ───────────────────────────────────────────────────────────────────────

class TestComputeRSI:
    def test_insufficient_data_returns_50(self):
        """< period+1 closes → neutral RSI 50."""
        assert _compute_rsi([100, 101, 102], period=14) == 50.0

    def test_all_gains_returns_near_100(self):
        """Monotonically increasing → RSI close to 100."""
        closes = [float(i) for i in range(100)]  # 0, 1, 2, ..., 99
        rsi = _compute_rsi(closes, period=14)
        assert rsi > 95  # Should be very high

    def test_all_losses_returns_near_0(self):
        """Monotonically decreasing → RSI close to 0."""
        closes = [float(100 - i) for i in range(100)]  # 100, 99, 98, ..., 1
        rsi = _compute_rsi(closes, period=14)
        assert rsi < 5  # Should be very low

    def test_sideways_market_around_50(self):
        """Alternating up/down → RSI around 50."""
        closes = []
        for i in range(100):
            closes.append(100 + (1 if i % 2 == 0 else -1))
        rsi = _compute_rsi(closes, period=14)
        assert 40 < rsi < 60

    def test_rsi_bounded_0_100(self):
        """RSI must always be between 0 and 100."""
        import random
        random.seed(42)
        closes = [100 + random.uniform(-10, 10) for _ in range(200)]
        rsi = _compute_rsi(closes, period=14)
        assert 0 <= rsi <= 100

    def test_custom_period(self):
        closes = [float(i) for i in range(50)]
        rsi_14 = _compute_rsi(closes, period=14)
        rsi_7 = _compute_rsi(closes, period=7)
        # Shorter period → more responsive → higher for uptrend
        assert rsi_7 >= rsi_14


# ── MACD ──────────────────────────────────────────────────────────────────────

class TestComputeMACD:
    def test_insufficient_data(self):
        """< 26 closes → (0, 0)."""
        macd, signal = _compute_macd([100] * 25)
        assert macd == 0.0
        assert signal == 0.0

    def test_flat_market_near_zero(self):
        """Constant price → MACD ≈ 0."""
        closes = [100.0] * 100
        macd, signal = _compute_macd(closes)
        assert abs(macd) < 0.01
        assert abs(signal) < 0.01

    def test_uptrend_positive_macd(self):
        """Strong uptrend → positive MACD (12 EMA > 26 EMA)."""
        closes = [float(100 + i * 2) for i in range(100)]
        macd, signal = _compute_macd(closes)
        assert macd > 0

    def test_downtrend_negative_macd(self):
        """Strong downtrend → negative MACD."""
        closes = [float(200 - i * 2) for i in range(100)]
        macd, signal = _compute_macd(closes)
        assert macd < 0

    def test_returns_float_tuple(self):
        closes = [100 + i * 0.5 for i in range(100)]
        result = _compute_macd(closes)
        assert isinstance(result, tuple)
        assert len(result) == 2
        assert isinstance(result[0], float)
        assert isinstance(result[1], float)

    def test_no_index_error_on_edge_cases(self):
        """Exactly 26 closes should not crash."""
        macd, signal = _compute_macd([100.0] * 26)
        # Might return 0 if not enough for signal, but must not crash
        assert isinstance(macd, float)

    def test_exactly_35_closes(self):
        """26 + 9 = 35 minimum for full MACD + signal."""
        closes = [100 + i * 0.1 for i in range(35)]
        macd, signal = _compute_macd(closes)
        assert isinstance(macd, float)
        assert isinstance(signal, float)


# ── SMA ───────────────────────────────────────────────────────────────────────

class TestComputeSMA:
    def test_insufficient_data(self):
        assert _compute_sma([100, 101], period=50) == 0.0

    def test_exact_period(self):
        closes = [10.0, 20.0, 30.0]
        assert _compute_sma(closes, period=3) == pytest.approx(20.0)

    def test_uses_last_n_bars(self):
        """SMA should use the LAST period bars."""
        closes = [1, 2, 3, 10, 20, 30]
        sma3 = _compute_sma(closes, period=3)
        assert sma3 == pytest.approx(20.0)  # (10 + 20 + 30) / 3

    def test_single_value(self):
        assert _compute_sma([42.0], period=1) == pytest.approx(42.0)


# ── Signal ────────────────────────────────────────────────────────────────────

class TestComputeSignal:
    def test_strong_buy(self):
        """RSI < 30 AND MACD bullish → Strong Buy."""
        assert _compute_signal(rsi=25, macd_val=1.0, sig_val=0.5) == "Strong Buy"

    def test_buy_low_rsi(self):
        """RSI < 45 → Buy."""
        assert _compute_signal(rsi=40, macd_val=-0.5, sig_val=0.5) == "Buy"

    def test_buy_macd_bullish(self):
        """MACD bullish → Buy."""
        assert _compute_signal(rsi=55, macd_val=1.0, sig_val=0.5) == "Buy"

    def test_sell(self):
        """RSI > 70 AND MACD bearish → Sell."""
        assert _compute_signal(rsi=75, macd_val=-0.5, sig_val=0.5) == "Sell"

    def test_neutral(self):
        """RSI 50-70 AND MACD bearish → Neutral."""
        assert _compute_signal(rsi=55, macd_val=-0.5, sig_val=0.5) == "Neutral"


# ── Filter matchers ───────────────────────────────────────────────────────────

class TestMatchesRSI:
    def test_oversold(self):
        assert _matches_rsi(25, "oversold") is True
        assert _matches_rsi(35, "oversold") is False

    def test_neutral(self):
        assert _matches_rsi(50, "neutral") is True
        assert _matches_rsi(25, "neutral") is False
        assert _matches_rsi(75, "neutral") is False

    def test_overbought(self):
        assert _matches_rsi(75, "overbought") is True
        assert _matches_rsi(65, "overbought") is False

    def test_any(self):
        assert _matches_rsi(50, "any") is True
        assert _matches_rsi(10, "any") is True


class TestMatchesVolume:
    def test_high_volume(self):
        assert _matches_volume(2.0, "1.5x") is True
        assert _matches_volume(1.0, "1.5x") is False

    def test_any(self):
        assert _matches_volume(0.1, "any") is True


class TestMatchesMACD:
    def test_buy_signal(self):
        assert _matches_macd(1.0, 0.5, "buy") is True  # MACD > signal
        assert _matches_macd(0.5, 1.0, "buy") is False

    def test_sell_signal(self):
        assert _matches_macd(0.5, 1.0, "sell") is True  # MACD < signal
        assert _matches_macd(1.0, 0.5, "sell") is False

    def test_any(self):
        assert _matches_macd(0, 0, "any") is True


class TestMatchesPrice:
    def test_above_ma200(self):
        assert _matches_price(150, 100, 120, "above_ma200") is True  # close > ma200
        assert _matches_price(100, 120, 150, "above_ma200") is False

    def test_below_ma200(self):
        assert _matches_price(100, 120, 150, "below_ma200") is True  # close < ma200
        assert _matches_price(200, 120, 150, "below_ma200") is False

    def test_above_ma50(self):
        assert _matches_price(110, 100, 120, "above_ma50") is True  # close > ma50
        assert _matches_price(90, 100, 120, "above_ma50") is False

    def test_any(self):
        assert _matches_price(100, 200, 300, "any") is True
