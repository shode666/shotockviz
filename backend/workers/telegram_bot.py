"""Long-polling Telegram bot listener — bd:features-2026-09 slice 3 (Sara
ADR-T1). Runs as its own long-lived compose service (`telegram-bot`), NOT
inside Celery — reuses `python-telegram-bot`'s async `Application` event
loop directly, same pattern-shape as the other backend-adjacent long-running
processes (`celery-worker`/`celery-beat` in docker-compose.dev.yml), just
without Celery itself since there's no task queue involved here.

Stateless (Sara ADR-T4): the bot does NOT touch the DB. `/start` replies
with `chat.id` as plain text; the user pastes it into SettingsPage
themselves (matches the shipped hint text,
frontend/src/components/pages/SettingsPage.tsx:145-147). No webhook
(dev is not publicly reachable — caddy/Caddyfile.dev:3-4 `tls internal`),
no account-linking flow, no conversation state.

Run: `python -m workers.telegram_bot`
"""
from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)


async def start_handler(update, context) -> None:
    """Reply with the sender's chat id as plain text."""
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"Chat ID ของคุณคือ: `{chat_id}`\n"
        "นำไปวางใน Settings > Notification เพื่อรับ alert ผ่าน Telegram",
        parse_mode="Markdown",
    )


async def fallback_handler(update, context) -> None:
    """Any non-/start message — point back to /start."""
    await update.message.reply_text("พิมพ์ /start เพื่อรับ chat id ของคุณ")


def main() -> None:
    if not settings.telegram_bot_token:
        # Don't crash-loop under `restart: unless-stopped` when the token
        # is simply not configured yet (dev bootstrap, CI, etc).
        logger.warning("TELEGRAM_BOT_TOKEN not set — telegram-bot listener exiting")
        return

    from telegram import Update
    from telegram.ext import Application, CommandHandler, MessageHandler, filters

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(MessageHandler(filters.ALL, fallback_handler))

    logger.info("telegram-bot listener starting (long polling)")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
