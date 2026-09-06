"""Tests for bd:shotockviz-60p — creating an alert whose condition is
ALREADY true right now used to be accepted silently and fire on the very
next check_all_alerts tick, then again every `alert_cooldown_minutes`
forever (alerts are standing, not one-shot — bd:shotockviz-93h). This
covers both the pure helper (`_current_condition_state`) and the
end-to-end 409-vs-201 behavior of `POST /api/v1/alerts`.
"""
from unittest.mock import AsyncMock, patch

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from api.routes.alerts import _current_condition_state
from models.alert import AlertType
from models.user import User


def _bars(closes, volumes=None):
    volumes = volumes or [1_000_000.0] * len(closes)
    return [
        {"time": f"2026-01-{i + 1:02d}", "open": c, "high": c, "low": c, "close": c, "volume": v}
        for i, (c, v) in enumerate(zip(closes, volumes))
    ]


# ── Direct unit tests of _current_condition_state ───────────────────────────

class TestCurrentConditionStatePrice:
    @pytest.mark.asyncio
    async def test_price_above_already_true(self):
        with patch(
            "services.stock_service.read_quote",
            AsyncMock(return_value={"price": 230.0}),
        ):
            triggered, current, label = await _current_condition_state(
                "AAPL", AlertType.PRICE_ABOVE, 17.0
            )
        assert triggered is True
        assert current == 230.0
        assert label == "price"

    @pytest.mark.asyncio
    async def test_price_above_not_true(self):
        with patch(
            "services.stock_service.read_quote",
            AsyncMock(return_value={"price": 10.0}),
        ):
            triggered, current, _ = await _current_condition_state(
                "AAPL", AlertType.PRICE_ABOVE, 17.0
            )
        assert triggered is False
        assert current == 10.0

    @pytest.mark.asyncio
    async def test_price_below_already_true(self):
        with patch(
            "services.stock_service.read_quote",
            AsyncMock(return_value={"price": 5.0}),
        ):
            triggered, current, _ = await _current_condition_state(
                "AAPL", AlertType.PRICE_BELOW, 17.0
            )
        assert triggered is True
        assert current == 5.0

    @pytest.mark.asyncio
    async def test_quote_cache_miss_does_not_block_creation(self):
        """NO MAGIC — can't verify, so allow creation unconfirmed, same as
        before this bead (existing cache-miss philosophy elsewhere)."""
        with patch("services.stock_service.read_quote", AsyncMock(return_value=None)):
            triggered, current, _ = await _current_condition_state(
                "AAPL", AlertType.PRICE_ABOVE, 17.0
            )
        assert triggered is False
        assert current is None

    @pytest.mark.asyncio
    async def test_value_none_short_circuits(self):
        triggered, current, label = await _current_condition_state(
            "AAPL", AlertType.PRICE_ABOVE, None
        )
        assert (triggered, current, label) == (False, None, "")


class TestCurrentConditionStateIndicator:
    @pytest.mark.asyncio
    async def test_rsi_oversold_already_true_on_closed_bars(self):
        closes = [float(100 - i) for i in range(100)]  # RSI == 0.0 (all losses)
        with (
            patch("services.stock_service.read_history", AsyncMock(return_value=_bars(closes))),
            patch("workers.alert_checker._is_market_open_for", return_value=False),
        ):
            triggered, rsi, label = await _current_condition_state(
                "NVDA", AlertType.RSI_OVERSOLD, 1.0
            )
        assert triggered is True
        assert label == "RSI_OVERSOLD"
        assert rsi == 0.0

    @pytest.mark.asyncio
    async def test_indicator_forming_bar_excluded_bd_1sf(self):
        """The creation-time check must not fabricate a cross off the
        still-forming bar either — reuses the same _drop_forming_bar the
        checker worker uses (bd:shotockviz-1sf)."""
        closes = [100.0] * 50 + [130.0]  # cross only if the last bar counts
        with (
            patch("services.stock_service.read_history", AsyncMock(return_value=_bars(closes))),
            patch("workers.alert_checker._is_market_open_for", return_value=True),
        ):
            triggered, _, _ = await _current_condition_state(
                "NVDA", AlertType.GOLDEN_CROSS, None
            )
        # forming bar dropped -> back to 50 flat bars -> insufficient for
        # the cross definition (< 51) -> never claims "already true"
        assert triggered is False

    @pytest.mark.asyncio
    async def test_history_cache_miss_does_not_block_creation(self):
        with patch("services.stock_service.read_history", AsyncMock(return_value=[])):
            triggered, current, _ = await _current_condition_state(
                "NVDA", AlertType.RSI_OVERSOLD, 1.0
            )
        assert triggered is False
        assert current is None


# ── End-to-end: POST /api/v1/alerts ──────────────────────────────────────────

@pytest.mark.asyncio
class TestCreateAlertAlreadyTrueGuard:
    async def test_already_true_price_alert_refused_with_409(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db,
        test_user: User, auth_headers: dict,
    ):
        with patch(
            "services.stock_service.read_quote",
            AsyncMock(return_value={"price": 230.0}),
        ):
            response = await async_client.post(
                "/api/v1/alerts",
                json={
                    "symbol": "AAPL",
                    "alert_type": "PRICE_ABOVE",
                    "condition": "above",
                    "value": 17.0,
                    "channel": "TELEGRAM",
                },
                headers=auth_headers,
            )

        assert response.status_code == 409
        detail = response.json()["meta"]["error"]["message"]
        assert "230.0" in detail or "230" in detail

    async def test_already_true_price_alert_created_when_confirmed(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db,
        test_user: User, auth_headers: dict,
    ):
        with patch(
            "services.stock_service.read_quote",
            AsyncMock(return_value={"price": 230.0}),
        ):
            response = await async_client.post(
                "/api/v1/alerts",
                json={
                    "symbol": "AAPL",
                    "alert_type": "PRICE_ABOVE",
                    "condition": "above",
                    "value": 17.0,
                    "channel": "TELEGRAM",
                    "confirm": True,
                },
                headers=auth_headers,
            )

        assert response.status_code == 201
        body = response.json()["data"]
        assert body["symbol"] == "AAPL"
        assert body["value"] == 17.0

    async def test_not_already_true_created_without_confirm(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db,
        test_user: User, auth_headers: dict,
    ):
        with patch(
            "services.stock_service.read_quote",
            AsyncMock(return_value={"price": 10.0}),
        ):
            response = await async_client.post(
                "/api/v1/alerts",
                json={
                    "symbol": "AAPL",
                    "alert_type": "PRICE_ABOVE",
                    "condition": "above",
                    "value": 17.0,
                    "channel": "TELEGRAM",
                },
                headers=auth_headers,
            )

        assert response.status_code == 201

    async def test_quote_unavailable_created_without_confirm(
        self, async_client: AsyncClient, test_db: AsyncSession, override_db,
        test_user: User, auth_headers: dict,
    ):
        """Cache miss must not block creation — NO MAGIC, can't verify."""
        with patch("services.stock_service.read_quote", AsyncMock(return_value=None)):
            response = await async_client.post(
                "/api/v1/alerts",
                json={
                    "symbol": "AAPL",
                    "alert_type": "PRICE_ABOVE",
                    "condition": "above",
                    "value": 17.0,
                    "channel": "TELEGRAM",
                },
                headers=auth_headers,
            )

        assert response.status_code == 201
