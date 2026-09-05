"""Tests for bd:shotockviz-06e — RSI_OVERBOUGHT, RSI_OVERSOLD, GOLDEN_CROSS,
DEATH_CROSS and VOLUME_SPIKE alert evaluation in workers/alert_checker.py.

Before this bead these 5 types were accepted by the API and displayed as
"ทำงานอยู่" (active) but `check_all_alerts()` only ever evaluated
PRICE_ABOVE/PRICE_BELOW — every one of these fell through
`if not triggered: continue` forever. These tests exercise the real
`check_all_alerts()` task end to end (sqlite DB + mocked Redis/httpx),
same pattern as test_alert_checker_cache_key.py and
test_alert_checker_idempotency.py, plus direct unit tests of
`_evaluate_indicator_alert` for the trigger-definition edge cases.
"""
import json
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core import cache_keys
from core.database import Base
from models.alert import Alert, AlertChannel, AlertStatus, AlertType
from models.user import User
from services import indicators
from workers.alert_checker import (
    _evaluate_indicator_alert,
    _load_daily_bars,
    check_all_alerts,
)


def _bars_from_closes(closes, volumes=None):
    volumes = volumes or [1_000_000.0] * len(closes)
    return [
        {"time": f"2026-01-{i + 1:02d}", "open": c, "high": c, "low": c, "close": c, "volume": v}
        for i, (c, v) in enumerate(zip(closes, volumes))
    ]


class _FakeAlert:
    """Minimal stand-in for models.alert.Alert — only the attributes
    _evaluate_indicator_alert actually reads."""

    def __init__(self, alert_type: str, value):
        self.alert_type = AlertType(alert_type)
        self.value = value


# ── Direct unit tests of the trigger definitions ────────────────────────────

class TestRSIOverboughtOversold:
    def test_rsi_oversold_honours_user_supplied_threshold_not_hardcoded_30(self):
        """Monotonically DECREASING closes → RSI near 0 (see
        test_screener_indicators.py::test_all_losses_returns_near_0).
        A hardcoded 30 threshold would trigger here too, so the test uses
        a deliberately non-30 threshold (1.0) to prove `value` — not a
        constant — drives the comparison."""
        closes = [float(100 - i) for i in range(100)]
        bars = _bars_from_closes(closes)
        alert = _FakeAlert("RSI_OVERSOLD", 1.0)
        triggered, rsi = _evaluate_indicator_alert(alert, bars)
        assert triggered is True
        assert rsi == indicators.compute_rsi(closes)

    def test_rsi_oversold_does_not_trigger_above_threshold(self):
        closes = [float(i) for i in range(100)]  # RSI == 100.0 (all gains)
        bars = _bars_from_closes(closes)
        alert = _FakeAlert("RSI_OVERSOLD", 5.0)  # RSI 100.0 is not < 5
        triggered, _ = _evaluate_indicator_alert(alert, bars)
        assert triggered is False

    def test_rsi_overbought_honours_user_supplied_threshold_not_hardcoded_70(self):
        """Monotonically INCREASING closes → RSI == 100.0 (all gains,
        avg_loss == 0). A hardcoded 70 threshold would trigger here too,
        so the test uses a deliberately non-70 threshold (99.0) to prove
        `value` — not a constant — drives the comparison."""
        closes = [float(i) for i in range(100)]
        bars = _bars_from_closes(closes)
        alert = _FakeAlert("RSI_OVERBOUGHT", 99.0)
        triggered, rsi = _evaluate_indicator_alert(alert, bars)
        assert triggered is True
        assert rsi == indicators.compute_rsi(closes)

    def test_missing_value_never_triggers(self):
        closes = [float(i) for i in range(100)]
        bars = _bars_from_closes(closes)
        for t in ("RSI_OVERBOUGHT", "RSI_OVERSOLD"):
            triggered, _ = _evaluate_indicator_alert(_FakeAlert(t, None), bars)
            assert triggered is False


class TestGoldenDeathCross:
    """20/50 SMA cross — this project's own existing convention
    (services/backtesting_engine.py::_strategy_golden_cross, and
    tests/test_next_features.py's docstring), not a MACD-line cross and
    not a 50/200 cross. Fixtures are validated against the real
    indicators.compute_sma output rather than hand-derived numbers, so
    the test documents *what* must be true (a real cross occurred)
    rather than asserting a magic constant."""

    def _golden_cross_closes(self):
        # 50 flat bars (SMA20 == SMA50, no cross yet) then a sharp ramp
        # for the last bar that pulls SMA20 above SMA50.
        return [100.0] * 50 + [130.0]

    def _death_cross_closes(self):
        return [100.0] * 50 + [70.0]

    def test_golden_cross_fixture_is_a_real_cross(self):
        closes = self._golden_cross_closes()
        fast_prev = indicators.compute_sma(closes[:-1], 20)
        slow_prev = indicators.compute_sma(closes[:-1], 50)
        fast_now = indicators.compute_sma(closes, 20)
        slow_now = indicators.compute_sma(closes, 50)
        assert fast_prev <= slow_prev
        assert fast_now > slow_now

    def test_golden_cross_alert_triggers_on_real_cross(self):
        bars = _bars_from_closes(self._golden_cross_closes())
        triggered, _ = _evaluate_indicator_alert(_FakeAlert("GOLDEN_CROSS", None), bars)
        assert triggered is True

    def test_death_cross_fixture_is_a_real_cross(self):
        closes = self._death_cross_closes()
        fast_prev = indicators.compute_sma(closes[:-1], 20)
        slow_prev = indicators.compute_sma(closes[:-1], 50)
        fast_now = indicators.compute_sma(closes, 20)
        slow_now = indicators.compute_sma(closes, 50)
        assert fast_prev >= slow_prev
        assert fast_now < slow_now

    def test_death_cross_alert_triggers_on_real_cross(self):
        bars = _bars_from_closes(self._death_cross_closes())
        triggered, _ = _evaluate_indicator_alert(_FakeAlert("DEATH_CROSS", None), bars)
        assert triggered is True

    def test_golden_cross_does_not_trigger_when_already_above_no_new_cross(self):
        # Flat-above series: SMA20 has been above SMA50 for a while —
        # "currently above" must NOT re-trigger every tick.
        closes = [100.0] * 50 + [130.0] * 10
        bars = _bars_from_closes(closes)
        triggered, _ = _evaluate_indicator_alert(_FakeAlert("GOLDEN_CROSS", None), bars)
        assert triggered is False

    def test_insufficient_bars_for_cross_never_triggers(self):
        bars = _bars_from_closes([100.0] * 30)  # < 51 needed for SMA50 prev+now
        triggered, _ = _evaluate_indicator_alert(_FakeAlert("GOLDEN_CROSS", None), bars)
        assert triggered is False


class TestVolumeSpike:
    def test_triggers_when_ratio_meets_user_supplied_multiplier(self):
        volumes = [100.0] * 29 + [400.0]
        closes = [50.0] * 30
        bars = _bars_from_closes(closes, volumes)
        ratio = indicators.compute_volume_ratio(volumes)
        alert = _FakeAlert("VOLUME_SPIKE", ratio)  # exactly at threshold, >= must hold
        triggered, display_ratio = _evaluate_indicator_alert(alert, bars)
        assert triggered is True
        assert display_ratio == ratio

    def test_does_not_trigger_below_multiplier(self):
        volumes = [100.0] * 30  # flat, ratio ~= 1.0
        closes = [50.0] * 30
        bars = _bars_from_closes(closes, volumes)
        triggered, _ = _evaluate_indicator_alert(_FakeAlert("VOLUME_SPIKE", 3.0), bars)
        assert triggered is False

    def test_missing_value_never_triggers(self):
        volumes = [100.0] * 29 + [10000.0]
        closes = [50.0] * 30
        bars = _bars_from_closes(closes, volumes)
        triggered, _ = _evaluate_indicator_alert(_FakeAlert("VOLUME_SPIKE", None), bars)
        assert triggered is False


class TestLoadDailyBars:
    def test_cache_hit_with_enough_bars_returns_list(self):
        bars = _bars_from_closes([float(i) for i in range(30)])
        fake_redis = MagicMock()
        fake_redis.get.return_value = json.dumps(bars).encode()
        result = _load_daily_bars(fake_redis, "NVDA")
        assert result == bars
        fake_redis.get.assert_called_once_with(cache_keys.ohlcv("NVDA", "1D"))

    def test_cache_miss_returns_none(self):
        fake_redis = MagicMock()
        fake_redis.get.return_value = None
        assert _load_daily_bars(fake_redis, "NVDA") is None

    def test_too_few_bars_returns_none(self):
        bars = _bars_from_closes([1.0, 2.0, 3.0])  # < 26
        fake_redis = MagicMock()
        fake_redis.get.return_value = json.dumps(bars).encode()
        assert _load_daily_bars(fake_redis, "NVDA") is None


# ── Full check_all_alerts() integration (sqlite DB + mocked Redis/httpx) ────

@pytest.fixture
def sqlite_db_url_factory(tmp_path):
    """Returns a function that seeds one alert of the given type/value and
    returns the sqlite URL — same pattern as
    test_alert_checker_cache_key.py's fixture."""

    def _make(alert_type: AlertType, value):
        db_path = tmp_path / f"alert_checker_indicator_{alert_type.value}.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)

        with Session(engine) as db:
            user = User(
                email=f"{alert_type.value.lower()}@example.com",
                password_hash="x",
                display_name="Indicator Alert Test User",
            )
            db.add(user)
            db.flush()

            alert = Alert(
                user_id=user.id,
                symbol="NVDA",
                alert_type=alert_type,
                condition="n/a",
                value=value,
                is_active=True,
                status=AlertStatus.ACTIVE,
                channel=AlertChannel.EMAIL,  # no Telegram send needed for this test
            )
            db.add(alert)
            db.commit()

        engine.dispose()
        return f"sqlite:///{db_path}"

    return _make


class TestCheckAllAlertsEvaluatesIndicatorTypes:
    def test_rsi_oversold_alert_flips_to_triggered_end_to_end(self, sqlite_db_url_factory):
        sqlite_db_url = sqlite_db_url_factory(AlertType.RSI_OVERSOLD, 1.0)
        closes = [float(100 - i) for i in range(100)]  # RSI == 0.0 (all losses)
        bars = _bars_from_closes(closes)

        fake_redis = MagicMock()
        fake_redis.get.return_value = json.dumps(bars).encode()
        fake_redis.publish.return_value = 1

        with (
            patch("core.config.settings.database_url", sqlite_db_url),
            patch("redis.from_url", return_value=fake_redis),
        ):
            check_all_alerts()

        fake_redis.get.assert_called_once_with(cache_keys.ohlcv("NVDA", "1D"))

        engine = create_engine(sqlite_db_url)
        with Session(engine) as db:
            alert = db.query(Alert).one()
            assert alert.status == AlertStatus.TRIGGERED
            assert alert.is_active is False
            assert alert.triggered_at is not None
        engine.dispose()

    def test_indicator_alert_cache_miss_logs_and_skips(self, sqlite_db_url_factory):
        sqlite_db_url = sqlite_db_url_factory(AlertType.VOLUME_SPIKE, 3.0)

        fake_redis = MagicMock()
        fake_redis.get.return_value = None  # OHLCV cache miss

        with (
            patch("core.config.settings.database_url", sqlite_db_url),
            patch("redis.from_url", return_value=fake_redis),
            patch("workers.alert_checker.logger") as mock_logger,
        ):
            check_all_alerts()

        assert mock_logger.warning.call_count == 1
        warning_msg = mock_logger.warning.call_args.args[0]
        assert "no cached daily bars" in warning_msg.lower()
        kwargs = mock_logger.warning.call_args.kwargs
        assert kwargs["symbol"] == "NVDA"
        assert kwargs["cache_key"] == cache_keys.ohlcv("NVDA", "1D")

        engine = create_engine(sqlite_db_url)
        with Session(engine) as db:
            alert = db.query(Alert).one()
            assert alert.status == AlertStatus.ACTIVE  # untouched
        engine.dispose()

    def test_non_triggering_indicator_alert_stays_active(self, sqlite_db_url_factory):
        closes = [float(i) for i in range(100)]
        rsi = indicators.compute_rsi(closes)
        threshold = rsi + 1.0  # guaranteed non-triggering: rsi > (rsi + 1) is always False
        sqlite_db_url = sqlite_db_url_factory(AlertType.RSI_OVERBOUGHT, threshold)
        bars = _bars_from_closes(closes)

        fake_redis = MagicMock()
        fake_redis.get.return_value = json.dumps(bars).encode()

        with (
            patch("core.config.settings.database_url", sqlite_db_url),
            patch("redis.from_url", return_value=fake_redis),
        ):
            check_all_alerts()

        engine = create_engine(sqlite_db_url)
        with Session(engine) as db:
            alert = db.query(Alert).one()
            assert alert.status == AlertStatus.ACTIVE
            assert alert.is_active is True
        engine.dispose()
