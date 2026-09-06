"""The one place this project sends an outbound Telegram message.

bd:shotockviz-4d9. Before this, five call sites each built the API URL and
POSTed it themselves — `alert_checker`, `sr_proximity_digest`,
`pipeline_health`, `gap_list_digest`, and the account-linking confirmation in
`api/routes/auth.py`. That is the same shape of problem as the five
hand-rolled fund-NAV dicts (bd:shotockviz-ubw): a rule that has to hold in
five places holds in four.

The rule that has to hold here is: **do not send real Telegram messages from
a developer's laptop.** The dev stack carries a real `TELEGRAM_BOT_TOKEN` and
the dev DB's user 1 has the same live `telegram_chat_id` as production, so
every scheduled notification in this project reaches the user's actual phone
from dev. On 2026-09-06 two S/R digests did exactly that — at 02:30 and 12:30
on a Sunday — and the only guard in place was a sentence in CLAUDE.md telling
agents not to send. A rule an agent has to remember is not a guard.

So: one chokepoint, honouring `settings.telegram_is_dry_run`. In dry run the
message is logged in full, with the chat id, at INFO — the developer sees
exactly what would have gone out, which is more useful than a silent no-op
and is what makes the suppression verifiable rather than assumed.
"""
from __future__ import annotations

from core.config import settings
from core.logger import get_logger

logger = get_logger(__name__)

TELEGRAM_API = "https://api.telegram.org"


def send_telegram_message(chat_id: str, text: str, *, context: str = "") -> bool:
    """Send one message; one retry; never raises. Returns whether it was sent.

    In dry run the return value is True: the caller's own bookkeeping (a
    run-lock already claimed, a `triggered_at` already committed) should treat
    a suppressed send as a completed one, or dev would loop retrying forever
    on a message that is never going to leave.
    """
    if settings.telegram_is_dry_run:
        logger.info(
            "TELEGRAM DRY RUN — message NOT sent",
            chat_id=chat_id,
            context=context,
            app_env=settings.app_env,
            text=text,
        )
        return True

    if not settings.telegram_bot_token:
        logger.warning("Telegram bot token not configured, cannot send", context=context)
        return False

    import httpx

    url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/sendMessage"
    last_error = None
    for _attempt in range(2):
        try:
            resp = httpx.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
            if resp.status_code == 200:
                logger.info("Telegram message sent", chat_id=chat_id, context=context)
                return True
            last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except httpx.HTTPError as e:
            last_error = str(e)

    logger.error(
        "Failed to send Telegram message after retry",
        chat_id=chat_id,
        context=context,
        error=last_error,
    )
    return False


async def send_telegram_message_async(chat_id: str, text: str, *, context: str = "") -> tuple[bool, str]:
    """Async twin for the FastAPI request path (account linking).

    Returns (ok, error_detail) because that call site reports the failure
    reason back to the user who is trying to link their account — a detail
    the fire-and-forget worker path has no use for.
    """
    if settings.telegram_is_dry_run:
        logger.info(
            "TELEGRAM DRY RUN — message NOT sent",
            chat_id=chat_id,
            context=context,
            app_env=settings.app_env,
            text=text,
        )
        return True, ""

    if not settings.telegram_bot_token:
        return False, "TELEGRAM_BOT_TOKEN not configured"

    import httpx

    url = f"{TELEGRAM_API}/bot{settings.telegram_bot_token}/sendMessage"
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            resp = await client.post(url, json={"chat_id": chat_id, "text": text})
        if resp.status_code != 200:
            body = (
                resp.json()
                if resp.headers.get("content-type", "").startswith("application/json")
                else {}
            )
            return False, body.get("description", f"HTTP {resp.status_code}")
        return True, ""
    except httpx.HTTPError as e:
        logger.warning("Telegram send failed", chat_id=chat_id, context=context, error=str(e))
        return False, str(e)
