"""Tests for GET/PATCH /api/v1/auth/settings — bd:features-2026-09 slice 3.

Follows the async_client + override_db + auth_headers fixture pattern from
conftest.py (same pattern test_sr_levels_endpoint.py / alerts.py routes use).
Telegram's sendMessage call is mocked — no real network access to
api.telegram.org.
"""
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from models.user import User


@pytest.mark.asyncio
class TestGetSettings:
    async def test_returns_null_when_not_set(
        self, async_client: AsyncClient, test_user: User, auth_headers: dict, override_db
    ):
        response = await async_client.get("/api/v1/auth/settings", headers=auth_headers)
        assert response.status_code == 200
        assert response.json()["data"]["telegram_chat_id"] is None

    async def test_requires_auth(self, async_client: AsyncClient, override_db):
        response = await async_client.get("/api/v1/auth/settings")
        assert response.status_code == 401


@pytest.mark.asyncio
class TestUpdateSettings:
    async def test_save_sends_telegram_test_message_and_persists(
        self, async_client: AsyncClient, test_user: User, auth_headers: dict,
        test_db: AsyncSession, override_db,
    ):
        mock_response = MagicMock(status_code=200)
        with (
            patch("core.config.settings.telegram_bot_token", "fake-token"),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            response = await async_client.patch(
                "/api/v1/auth/settings",
                json={"telegram_chat_id": "128845067"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        assert response.json()["data"]["telegram_chat_id"] == "128845067"
        mock_client.post.assert_awaited_once()
        call_kwargs = mock_client.post.call_args.kwargs
        assert call_kwargs["json"]["chat_id"] == "128845067"

        await test_db.refresh(test_user)
        assert test_user.telegram_chat_id == "128845067"

    async def test_save_does_not_persist_when_telegram_send_fails(
        self, async_client: AsyncClient, test_user: User, auth_headers: dict,
        test_db: AsyncSession, override_db,
    ):
        """Bad chat_id / bot never contacted -> clear error, no broken save."""
        mock_response = MagicMock(status_code=400)
        mock_response.headers = {"content-type": "application/json"}
        mock_response.json.return_value = {"description": "Bad Request: chat not found"}
        with (
            patch("core.config.settings.telegram_bot_token", "fake-token"),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            response = await async_client.patch(
                "/api/v1/auth/settings",
                json={"telegram_chat_id": "999999999"},
                headers=auth_headers,
            )

            mock_client.post.assert_awaited_once()

        assert response.status_code == 422
        assert "ไม่สำเร็จ" in response.json()["meta"]["error"]["message"]
        assert "chat not found" in response.json()["meta"]["error"]["message"]

        await test_db.refresh(test_user)
        assert test_user.telegram_chat_id is None

    async def test_clearing_chat_id_does_not_call_telegram(
        self, async_client: AsyncClient, test_user: User, auth_headers: dict,
        test_db: AsyncSession, override_db,
    ):
        test_user.telegram_chat_id = "111111"
        await test_db.commit()

        with patch("httpx.AsyncClient") as mock_client_cls:
            response = await async_client.patch(
                "/api/v1/auth/settings",
                json={"telegram_chat_id": None},
                headers=auth_headers,
            )
            mock_client_cls.assert_not_called()

        assert response.status_code == 200
        assert response.json()["data"]["telegram_chat_id"] is None

    async def test_rejects_non_numeric_chat_id(
        self, async_client: AsyncClient, test_user: User, auth_headers: dict, override_db
    ):
        response = await async_client.patch(
            "/api/v1/auth/settings",
            json={"telegram_chat_id": "not-a-number"},
            headers=auth_headers,
        )
        assert response.status_code == 422

    async def test_save_does_not_persist_when_network_is_down(
        self, async_client: AsyncClient, test_user: User, auth_headers: dict,
        test_db: AsyncSession, override_db,
    ):
        """Quinn Finding 2 (Chris, High) — the `httpx.HTTPError` (network
        down / DNS failure / timeout, NOT a well-formed non-200 response)
        path in `_send_telegram_test_message` was untested. `client.post`
        raising `httpx.ConnectError` must still produce a clear 422, not an
        unhandled 500, and must not silently persist a broken chat id."""
        with (
            patch("core.config.settings.telegram_bot_token", "fake-token"),
            patch("httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(
                side_effect=httpx.ConnectError("Connection refused")
            )
            mock_client_cls.return_value.__aenter__.return_value = mock_client

            response = await async_client.patch(
                "/api/v1/auth/settings",
                json={"telegram_chat_id": "128845067"},
                headers=auth_headers,
            )

        assert response.status_code == 422
        assert "ไม่สำเร็จ" in response.json()["meta"]["error"]["message"]
        assert "Connection refused" in response.json()["meta"]["error"]["message"]

        await test_db.refresh(test_user)
        assert test_user.telegram_chat_id is None
