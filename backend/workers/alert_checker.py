"""Celery task for checking price/indicator alerts."""
import asyncio
from datetime import datetime, timezone
from celery import shared_task
from core.logger import get_logger

logger = get_logger(__name__)


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def check_all_alerts(self):
    """Check all active alerts and trigger notifications if conditions met."""
    try:
        import redis
        import json
        import asyncio
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

                    if triggered:
                        alert.status = AlertStatus.TRIGGERED
                        alert.triggered_at = datetime.now(timezone.utc)
                        alert.is_active = False
                        db.commit()

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

                        # Send Telegram notification
                        _send_telegram_alert(alert, price)
                        logger.info("Alert triggered", alert_id=alert.id, symbol=alert.symbol)

                except Exception as e:
                    logger.warning("Failed to check alert", alert_id=alert.id, error=str(e))

    except Exception as exc:
        logger.error("Alert checker failed", error=str(exc))
        raise self.retry(exc=exc)


def _send_telegram_alert(alert, current_price: float):
    """Send Telegram notification for triggered alert."""
    try:
        from core.config import settings
        import httpx

        if not settings.telegram_bot_token:
            return

        # Get user's Telegram chat ID (would need to be stored per user)
        # For now, log the alert
        logger.info(
            "Alert triggered - Telegram notification",
            symbol=alert.symbol,
            type=alert.alert_type.value,
            price=current_price,
            target=alert.value,
        )
    except Exception as e:
        logger.error("Failed to send Telegram alert", error=str(e))
