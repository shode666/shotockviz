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
        logger.warning("TELEGRAM_BOT_TOKEN not set — telegram-bot listener not started")
        return False

    # bd:shotockviz-zz8 — only ONE process may long-poll a bot token.
    # python-telegram-bot's `getUpdates` allows a single consumer, so a dev
    # stack and production sharing one token kill each other's poll in a
    # loop: 9 `telegram.error.Conflict: terminated by other getUpdates
    # request` tracebacks in 5 minutes on each side, observed 2026-09-06.
    # The damage is not only log noise — `/start` is how the trader obtains
    # their chat id, and whichever instance wins the race answers it, so a
    # reply can come from a laptop instead of production, or not at all.
    #
    # `telegram_is_dry_run` is reused rather than inventing a second switch:
    # it already means "this environment must not act on the real bot", and
    # bd:shotockviz-4d9 established it for the OUTBOUND half (sends). This is
    # the inbound half that chokepoint could not cover. Enforced here rather
    # than by deleting the service from `docker-compose.dev.yml`, because a
    # compose-level fix breaks again the moment anyone runs the prod compose
    # locally — the same reason 4d9 rejected "a rule in CLAUDE.md".
    #
    # Returns False rather than exiting the process: under
    # `restart: unless-stopped` a clean exit is still a restart, and the
    # container relaunched every ~3 seconds logging this same line forever
    # (measured on the dev stack before `_idle_forever` below was added).
    # A service that is deliberately not working should sit still and say so
    # once, not flap.
    if settings.telegram_is_dry_run:
        logger.warning(
            "telegram-bot listener NOT started — this environment is "
            "dry-run, so it must not consume the bot's getUpdates stream "
            "(only one instance may poll a token). Set APP_ENV=production, "
            "or TELEGRAM_DRY_RUN=false, to poll from here instead.",
            app_env=settings.app_env,
        )
        return False

    from telegram import Update
    from telegram.ext import Application, CommandHandler, MessageHandler, filters

    application = Application.builder().token(settings.telegram_bot_token).build()
    application.add_handler(CommandHandler("start", start_handler))
    application.add_handler(MessageHandler(filters.ALL, fallback_handler))

    logger.info("telegram-bot listener starting (long polling)")
    application.run_polling(allowed_updates=Update.ALL_TYPES)
    return True


def _idle_forever() -> None:
    """Block without polling, so a deliberately-inactive listener stays up.

    bd:shotockviz-zz8 — `main()` returning is not the same as the process
    ending well: `restart: unless-stopped` restarts a clean exit too, so the
    container flapped every ~3 seconds and repeated its explanation forever.
    Idling keeps the one log line meaningful and the container's state honest
    (up, and deliberately doing nothing) instead of "restarting".
    """
    import threading

    threading.Event().wait()


if __name__ == "__main__":
    if not main():
        _idle_forever()
