"""Tests for bd:shotockviz-cm3(b) — workers/alert_symbol_refresher.py.

price_fetcher visits a given market slot roughly once every ~4-6 min;
alert_checker samples the quote cache every 60s. This task closes that
gap by refreshing quotes for symbols that have an ACTIVE PRICE_ABOVE/
PRICE_BELOW alert every 60s, gated to symbols whose market is currently
open (so it does not poll Yahoo Finance for a closed market forever).
"""
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from core.database import Base
from models.alert import Alert, AlertChannel, AlertStatus, AlertType
from models.user import User
from workers.alert_symbol_refresher import (
    _get_active_price_alert_symbols,
    _is_market_open_for,
    refresh_alert_symbols,
)


class TestIsMarketOpenFor:
    # A known-open SET moment: Tue 2026-09-08 04:00 UTC = 11:00 ICT.
    _SET_OPEN = datetime(2026, 9, 8, 4, 0, tzinfo=timezone.utc)
    # A known-closed moment for everything but crypto: Sat 2026-09-05 04:00 UTC.
    _WEEKEND = datetime(2026, 9, 5, 4, 0, tzinfo=timezone.utc)

    def test_thai_stock_open_during_set_hours(self):
        assert _is_market_open_for("PTT.BK", self._SET_OPEN) is True

    def test_thai_stock_closed_on_weekend(self):
        assert _is_market_open_for("PTT.BK", self._WEEKEND) is False

    def test_crypto_always_open(self):
        assert _is_market_open_for("BTC-USD", self._WEEKEND) is True

    def test_us_symbol_closed_on_weekend(self):
        assert _is_market_open_for("AAPL", self._WEEKEND) is False

    def test_asia_and_europe_suffixes_route_to_their_own_hours(self):
        # Just confirm these don't fall through to the US catch-all —
        # exact hour boundaries are price_fetcher's own tested territory.
        from workers.price_fetcher import _asia_hours, _eu_hours

        assert _is_market_open_for("7203.T", self._SET_OPEN) == _asia_hours(self._SET_OPEN)
        assert _is_market_open_for("VOD.L", self._SET_OPEN) == _eu_hours(self._SET_OPEN)


class TestGetActivePriceAlertSymbols:
    def _seed(self, tmp_path, rows):
        """rows: list of (symbol, alert_type, status, is_active)."""
        db_path = tmp_path / "alert_symbol_refresher_test.db"
        engine = create_engine(f"sqlite:///{db_path}")
        Base.metadata.create_all(engine)

        with Session(engine) as db:
            user = User(email="refresher@example.com", password_hash="x", display_name="U")
            db.add(user)
            db.flush()
            for symbol, alert_type, alert_status, is_active in rows:
                db.add(Alert(
                    user_id=user.id,
                    symbol=symbol,
                    alert_type=alert_type,
                    condition="n/a",
                    value=1.0,
                    is_active=is_active,
                    status=alert_status,
                    channel=AlertChannel.EMAIL,
                ))
            db.commit()
        engine.dispose()
        return f"sqlite:///{db_path}"

    def test_only_active_price_alert_symbols_returned(self, tmp_path):
        sqlite_db_url = self._seed(tmp_path, [
            ("AAPL", AlertType.PRICE_ABOVE, AlertStatus.ACTIVE, True),
            ("NVDA", AlertType.PRICE_BELOW, AlertStatus.ACTIVE, True),
            # Indicator type — must NOT be included (reads OHLCV cache, not quote cache).
            ("TSLA", AlertType.RSI_OVERSOLD, AlertStatus.ACTIVE, True),
            # Inactive — must NOT be included.
            ("MSFT", AlertType.PRICE_ABOVE, AlertStatus.ACTIVE, False),
            # Already triggered — must NOT be included.
            ("GOOGL", AlertType.PRICE_ABOVE, AlertStatus.TRIGGERED, True),
        ])

        with patch("core.config.settings.database_url", sqlite_db_url):
            symbols = _get_active_price_alert_symbols()

        assert set(symbols) == {"AAPL", "NVDA"}

    def test_no_alerts_returns_empty_list(self, tmp_path):
        sqlite_db_url = self._seed(tmp_path, [])
        with patch("core.config.settings.database_url", sqlite_db_url):
            assert _get_active_price_alert_symbols() == []


class TestRefreshAlertSymbolsTask:
    def test_no_active_price_alerts_short_circuits(self):
        with patch(
            "workers.alert_symbol_refresher._get_active_price_alert_symbols",
            return_value=[],
        ):
            result = refresh_alert_symbols()
        assert result == {"symbols": 0, "open": 0, "priced": 0}

    def test_closed_market_symbols_are_not_fetched(self):
        with (
            patch(
                "workers.alert_symbol_refresher._get_active_price_alert_symbols",
                return_value=["PTT.BK"],
            ),
            patch(
                "workers.alert_symbol_refresher._is_market_open_for",
                return_value=False,
            ),
        ):
            result = refresh_alert_symbols()
        assert result == {"symbols": 1, "open": 0, "priced": 0}

    def test_open_market_symbols_are_batch_fetched_and_cached(self):
        fake_redis = MagicMock()
        quotes = {"AAPL": {"symbol": "AAPL", "price": 230.0, "change": 1.0, "change_pct": 0.5, "volume": 1000}}

        with (
            patch(
                "workers.alert_symbol_refresher._get_active_price_alert_symbols",
                return_value=["AAPL"],
            ),
            patch(
                "workers.alert_symbol_refresher._is_market_open_for",
                return_value=True,
            ),
            patch("redis.from_url", return_value=fake_redis),
            patch(
                "workers.alert_symbol_refresher.yfinance_batch_quotes",
                return_value=quotes,
            ) as mock_fetch,
        ):
            result = refresh_alert_symbols()

        mock_fetch.assert_called_once_with(["AAPL"])
        assert result == {"symbols": 1, "open": 1, "priced": 1}
        fake_redis.setex.assert_called_once()
        fake_redis.publish.assert_called_once()
