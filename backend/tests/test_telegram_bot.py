"""Tests for backend/workers/telegram_bot.py — bd:features-2026-09 slice 3.

Bot is stateless (Sara ADR-T4): /start just echoes chat.id, no DB/Redis
involved. Tests exercise the handler functions directly with mock
Update/Context objects (python-telegram-bot's own test suite uses the
same style) — no real network call to api.telegram.org.
"""
from unittest.mock import AsyncMock, MagicMock

import pytest

from workers.telegram_bot import fallback_handler, start_handler


@pytest.mark.asyncio
class TestStartHandler:
    async def test_replies_with_chat_id(self):
        update = MagicMock()
        update.effective_chat.id = 128845067
        update.message.reply_text = AsyncMock()

        await start_handler(update, context=MagicMock())

        update.message.reply_text.assert_awaited_once()
        args, _kwargs = update.message.reply_text.call_args
        assert "128845067" in args[0]
        assert "Settings" in args[0]

    async def test_replies_with_negative_group_chat_id(self):
        """Telegram group chat ids are negative int64 — must still round-trip
        as plain text, not crash on formatting."""
        update = MagicMock()
        update.effective_chat.id = -100123456789
        update.message.reply_text = AsyncMock()

        await start_handler(update, context=MagicMock())

        args, _ = update.message.reply_text.call_args
        assert "-100123456789" in args[0]


@pytest.mark.asyncio
class TestFallbackHandler:
    async def test_points_back_to_start(self):
        update = MagicMock()
        update.message.reply_text = AsyncMock()

        await fallback_handler(update, context=MagicMock())

        args, _ = update.message.reply_text.call_args
        assert "/start" in args[0]
