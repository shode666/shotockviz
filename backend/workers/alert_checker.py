"""Celery task for checking price/indicator alerts."""
from datetime import datetime, timezone
from celery import shared_task
from core.logger import get_logger

logger = get_logger(__name__)


def claim_alert(db, alert_id: int) -> bool:
    """Atomically claim one ACTIVE alert for triggering — the DB row IS the
    dedupe key (bd:features-2026-09 slice 3, Sara ADR-T3).

    Returns True iff THIS call won the claim (rowcount==1) — only the
    winner may send a notification. Commits on every call (both the win
    and the lose path) so the row lock is released immediately, matching
    Postgres's row-level locking semantics for concurrent UPDATEs on the
    same row: exactly one concurrent caller gets rowcount==1.

    Extracted as a standalone function (rather than inlined in
    `check_all_alerts`) so the race condition itself is unit-testable
    without needing Celery/Redis machinery — see
    tests/test_alert_checker_idempotency.py.
    """
    from sqlalchemy import update
    from models.alert import Alert, AlertStatus

    result = db.execute(
        update(Alert)
        .where(
            Alert.id == alert_id,
            Alert.status == AlertStatus.ACTIVE,
            Alert.is_active == True,
        )
        .values(
            status=AlertStatus.TRIGGERED,
            is_active=False,
            triggered_at=datetime.now(timezone.utc),
        )
    )
    db.commit()
    return result.rowcount == 1


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def check_all_alerts(self):
    """Check all active alerts and trigger notifications if conditions met."""
    try:
        import redis
        import json
        from core.config import settings
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session
        from models.alert import Alert, AlertStatus

        r = redis.from_url(settings.redis_url)

        # Use sync SQLAlchemy for Celery
        sync_url = settings.database_url.replace("+asyncpg", "")
        engine = create_engine(sync_url)

        with Session(engine) as db:
            alerts = db.execute(
                select(Alert).where(Alert.is_active == True, Alert.status == AlertStatus.ACTIVE)
            ).scalars().all()

            for alert in alerts:
                try:
                    # Key must match price_fetcher._cache_and_publish() which stores
                    # at cache:quote:{sym}  (not plain quote:{sym})
                    cached = r.get(f"cache:quote:{alert.symbol}")
                    if not cached:
                        continue

                    quote = json.loads(cached)
                    price = quote.get("price", 0)

                    triggered = False
                    if alert.alert_type.value == "PRICE_ABOVE" and alert.value and price > alert.value:
                        triggered = True
                    elif alert.alert_type.value == "PRICE_BELOW" and alert.value and price < alert.value:
                        triggered = True

                    if not triggered:
                        continue

                    # bd:features-2026-09 slice 3 (Sara ADR-T3) — atomic
                    # conditional UPDATE replaces the old read-then-write flip.
                    # The plain SELECT above takes no row lock, and a retried
                    # task (self.retry, default_retry_delay=60) can land
                    # exactly on top of the next 60s beat tick — two
                    # overlapping runs could both read this alert as ACTIVE
                    # before either commits, and both send Telegram. This
                    # UPDATE is the dedupe key: rowcount==1 means THIS run
                    # won the claim; done BEFORE any notification is sent.
                    won_claim = claim_alert(db, alert.id)

                    if not won_claim:
                        # Another concurrent run already claimed this alert —
                        # skip silently, do not notify twice.
                        logger.info(
                            "Alert already claimed by another run, skipping",
                            alert_id=alert.id,
                            symbol=alert.symbol,
                        )
                        continue

                    # Publish WS notification via Redis so the backend broadcaster
                    # forwards it to the user's connected browser tab.
                    # Top-level "symbol" is used by broadcaster routing;
                    # "type":"alert_triggered" is handled by the frontend hook.
                    try:
                        ws_payload = json.dumps({
                            "type": "alert_triggered",
                            "symbol": alert.symbol,   # for broadcaster broadcast_price() routing
                            "data": {
                                "symbol": alert.symbol,
                                "condition": f"{alert.alert_type.value} {alert.value}",
                                "price": price,
                                "alert_id": alert.id,
                            },
                        })
                        r.publish("price_updates", ws_payload)
                    except Exception:
                        pass  # WS notification is best-effort

                    # Send Telegram notification — only this run (the one that
                    # won the atomic claim above) sends.
                    _send_telegram_alert(db, alert, price)
                    logger.info("Alert triggered", alert_id=alert.id, symbol=alert.symbol)

                except Exception as e:
                    logger.warning("Failed to check alert", alert_id=alert.id, error=str(e))

    except Exception as exc:
        logger.error("Alert checker failed", error=str(exc))
        raise self.retry(exc=exc)


def _send_telegram_alert(db, alert, current_price: float):
    """Send Telegram notification for a triggered alert.

    bd:features-2026-09 slice 3 (Sara spec §6) — looks up the alert's
    user's `telegram_chat_id`; skips silently (log only) if not set or the
    channel isn't TELEGRAM. `db` is the same sync Session `check_all_alerts`
    already has open (the task's loop doesn't eager-load `alert.user`).
    """
    try:
        from core.config import settings
        from models.alert import AlertChannel
        from models.user import User
        import httpx

        if alert.channel != AlertChannel.TELEGRAM:
            return

        if not settings.telegram_bot_token:
            logger.info("Telegram bot token not configured, skipping send", alert_id=alert.id)
            return

        user = db.get(User, alert.user_id)
        if not user or not user.telegram_chat_id:
            logger.info(
                "User has no telegram_chat_id set, skipping Telegram send",
                alert_id=alert.id,
                user_id=alert.user_id,
            )
            return

        text = (
            f"🔔 Alert: {alert.symbol}\n"
            f"{alert.alert_type.value} {alert.value}\n"
            f"Current price: {current_price}\n"
            f"Time: {datetime.now(timezone.utc).isoformat()}"
        )
        url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"

        # R1 (04-sara-telegram-spec.md §9) — 1 retry with short backoff;
        # a lost Telegram send after the DB commit is at-most-once and
        # accepted (outbox pattern is over-engineering for 1 user).
        last_error = None
        for _attempt in range(2):
            try:
                resp = httpx.post(
                    url,
                    json={"chat_id": user.telegram_chat_id, "text": text},
                    timeout=10,
                )
                if resp.status_code == 200:
                    logger.info(
                        "Telegram alert sent",
                        alert_id=alert.id,
                        symbol=alert.symbol,
                        type=alert.alert_type.value,
                        price=current_price,
                        target=alert.value,
                    )
                    return
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
            except httpx.HTTPError as e:
                last_error = str(e)

        logger.error(
            "Failed to send Telegram alert after retry",
            alert_id=alert.id,
            error=last_error,
        )
    except Exception as e:
        logger.error("Failed to send Telegram alert", error=str(e))
