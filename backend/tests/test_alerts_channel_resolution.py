"""Tests for bd:shotockviz-675 — api/routes/alerts.py::_resolve_channel
must reject 'in_app' (no longer an accepted value; see FR-ALERT-002),
while still accepting the channels the app actually delivers.
"""
import pytest
from fastapi import HTTPException

from api.routes.alerts import _resolve_channel, _resolve_alert_type
from models.alert import AlertChannel, AlertType


class TestResolveChannel:
    @pytest.mark.parametrize("raw", ["in_app", "IN_APP", "In_App"])
    def test_in_app_is_rejected_regardless_of_case(self, raw):
        with pytest.raises(HTTPException) as exc_info:
            _resolve_channel(raw)
        assert exc_info.value.status_code == 422
        assert "in_app" in exc_info.value.detail.lower()

    @pytest.mark.parametrize("raw,expected", [("telegram", AlertChannel.TELEGRAM), ("TELEGRAM", AlertChannel.TELEGRAM)])
    def test_telegram_accepted(self, raw, expected):
        assert _resolve_channel(raw) == expected

    def test_unknown_channel_still_raises_422(self):
        with pytest.raises(HTTPException) as exc_info:
            _resolve_channel("carrier_pigeon")
        assert exc_info.value.status_code == 422

    def test_error_message_does_not_advertise_in_app_as_a_valid_option(self):
        with pytest.raises(HTTPException) as exc_info:
            _resolve_channel("carrier_pigeon")
        assert "IN_APP" not in exc_info.value.detail


class TestResolveAlertType:
    """Not touched by this ticket's logic, but exercised here because the
    5 new alert types now actually matter — a regression here would
    silently reintroduce bd:shotockviz-06e."""

    @pytest.mark.parametrize("raw,expected", [
        ("Price Above", AlertType.PRICE_ABOVE),
        ("Price Below", AlertType.PRICE_BELOW),
        ("Golden Cross", AlertType.GOLDEN_CROSS),
        ("Death Cross", AlertType.DEATH_CROSS),
        ("Volume Spike", AlertType.VOLUME_SPIKE),
        ("GOLDEN_CROSS", AlertType.GOLDEN_CROSS),
        ("DEATH_CROSS", AlertType.DEATH_CROSS),
        ("VOLUME_SPIKE", AlertType.VOLUME_SPIKE),
        ("RSI_OVERSOLD", AlertType.RSI_OVERSOLD),
        ("RSI_OVERBOUGHT", AlertType.RSI_OVERBOUGHT),
    ])
    def test_accepts_known_types(self, raw, expected):
        assert _resolve_alert_type(raw) == expected

    @pytest.mark.parametrize("raw,expected", [
        ("RSI Below", AlertType.RSI_OVERSOLD),
        ("RSI Above", AlertType.RSI_OVERBOUGHT),
        ("rsi below", AlertType.RSI_OVERSOLD),
        ("rsi above", AlertType.RSI_OVERBOUGHT),
    ])
    def test_ui_rsi_labels_do_not_naively_normalize_and_need_the_override_map(self, raw, expected):
        """bd:shotockviz-06e — AlertsPage.tsx's own dropdown sends exactly
        "RSI Below"/"RSI Above". Naive uppercase+underscore gives
        "RSI_BELOW"/"RSI_ABOVE", which is not a valid AlertType — every
        RSI alert created through the real UI 422'd before the label
        override existed. This is the regression guard for that."""
        assert _resolve_alert_type(raw) == expected
