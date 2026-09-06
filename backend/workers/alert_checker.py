"""Celery task for checking price/indicator alerts."""
from datetime import datetime, timezone
from celery import shared_task
from core import cache_keys
from core.logger import get_logger
from services import indicators

logger = get_logger(__name__)

# bd:shotockviz-06e — alert types that read the OHLCV daily-bar cache
# (`ohlcv:{symbol}:1D`, kept warm by workers/history_prefetcher.py) instead
# of the quote cache. Same minimum-bars guard the screener already uses
# (api/routes/screener.py::_evaluate_symbol) — insufficient history means
# "skip, don't guess" rather than falling back to a neutral/zero value that
# could accidentally satisfy a threshold.
_INDICATOR_ALERT_TYPES = frozenset({
    "RSI_OVERBOUGHT", "RSI_OVERSOLD", "GOLDEN_CROSS", "DEATH_CROSS", "VOLUME_SPIKE",
})
_MIN_BARS_FOR_INDICATORS = 26


def _load_daily_bars(r, symbol: str) -> list[dict] | None:
    """Read the cached 1D OHLCV bars for `symbol`, or None on miss/short history.

    Mirrors the quote-cache-miss handling below: a miss here means every
    indicator-based alert for this symbol silently never fires until
    history_prefetcher warms the cache again — visible via the warning
    log, no retry/backfill added (same scope decision as the 983 fix).
    """
    import json

    cache_key = cache_keys.ohlcv(symbol, "1D")
    cached = r.get(cache_key)
    if not cached:
        return None
    try:
        bars = json.loads(cached)
    except (TypeError, ValueError):
        return None
    if not isinstance(bars, list) or len(bars) < _MIN_BARS_FOR_INDICATORS:
        return None
    return bars


def _evaluate_indicator_alert(alert, bars: list[dict]) -> tuple[bool, float]:
    """Evaluate one of the 5 non-price alert types against cached daily bars.

    Returns (triggered, display_value) — display_value is whatever number
    is most useful in the Telegram/WS payload (RSI value, SMA-20, or
    volume ratio); it is NOT the raw close price, unlike the PRICE_ABOVE/
    PRICE_BELOW path, since "current price" is not what these types react to.

    Trigger definitions (bd:shotockviz-06e, put in code per Oliver's ask,
    not just in a report):
      - RSI_OVERBOUGHT ("RSI Above" in the UI): RSI(14) > alert.value.
        alert.value is the user-supplied threshold — NOT a hardcoded 70.
      - RSI_OVERSOLD ("RSI Below" in the UI): RSI(14) < alert.value.
        alert.value is the user-supplied threshold — NOT a hardcoded 30.
      - GOLDEN_CROSS: SMA(20) crosses from <= SMA(50) to > SMA(50) between
        yesterday's close and today's — a true cross event (not merely
        "SMA20 is currently above SMA50", which would re-fire every tick
        once above). 20/50 matches this project's own existing precedent
        for "Golden/Death Cross" — services/backtesting_engine.py's
        `_strategy_golden_cross` (fast=20, slow=50) and the docstring in
        tests/test_next_features.py ("Golden Cross (20-SMA > 50-SMA)") —
        reused rather than inventing a second convention (e.g. 50/200).
      - DEATH_CROSS: SMA(20) crosses from >= SMA(50) to < SMA(50), same
        pair, opposite direction.
      - VOLUME_SPIKE: today's volume ÷ 20-day average volume >= alert.value.
        alert.value is the user-supplied multiplier (REQUIREMENTS.md
        FR-ALERT-001 example: "Volume > 3x avg") — NOT a hardcoded ratio.
        Same ratio the screener's Volume filter uses
        (services/indicators.compute_volume_ratio).
    """
    closes = [float(b["close"]) for b in bars]
    volumes = [float(b["volume"]) for b in bars]
    t = alert.alert_type.value

    if t == "RSI_OVERBOUGHT":
        if alert.value is None:
            return False, 0.0
        rsi = indicators.compute_rsi(closes)
        return rsi > alert.value, rsi

    if t == "RSI_OVERSOLD":
        if alert.value is None:
            return False, 0.0
        rsi = indicators.compute_rsi(closes)
        return rsi < alert.value, rsi

    if t in ("GOLDEN_CROSS", "DEATH_CROSS"):
        if len(closes) < 51:
            return False, 0.0
        fast_prev = indicators.compute_sma(closes[:-1], 20)
        slow_prev = indicators.compute_sma(closes[:-1], 50)
        fast_now = indicators.compute_sma(closes, 20)
        slow_now = indicators.compute_sma(closes, 50)
        # bd:shotockviz-0x0 — compute_sma now returns None (not 0.0) on
        # insufficient data. The len(closes) < 51 guard above should make
        # this unreachable, but never compare against/return a None SMA.
        if None in (fast_prev, slow_prev, fast_now, slow_now):
            return False, 0.0
        if t == "GOLDEN_CROSS":
            triggered = fast_prev <= slow_prev and fast_now > slow_now
        else:
            triggered = fast_prev >= slow_prev and fast_now < slow_now
        return triggered, fast_now

    if t == "VOLUME_SPIKE":
        if alert.value is None:
            return False, 0.0
        ratio = indicators.compute_volume_ratio(volumes)
        return ratio >= alert.value, ratio

    return False, 0.0


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
                    alert_type_value = alert.alert_type.value

                    if alert_type_value in _INDICATOR_ALERT_TYPES:
                        # bd:shotockviz-06e — RSI/Golden-Death-Cross/Volume-
                        # Spike read the daily OHLCV cache, not the quote
                        # cache; see _load_daily_bars / _evaluate_indicator_alert.
                        bars = _load_daily_bars(r, alert.symbol)
                        if bars is None:
                            logger.warning(
                                "Alert check: no cached daily bars, skipping",
                                alert_id=alert.id,
                                symbol=alert.symbol,
                                cache_key=cache_keys.ohlcv(alert.symbol, "1D"),
                                alert_type=alert_type_value,
                            )
                            continue
                        triggered, display_value = _evaluate_indicator_alert(alert, bars)
                        price = float(bars[-1]["close"])
                        if not triggered:
                            continue
                    else:
                        # bd:shotockviz-983 — must go through cache_keys.quote()
                        # (single source of truth, core/cache_keys.py) so this
                        # always matches whatever key price_fetcher's
                        # cache_and_publish_quotes() actually wrote under. A
                        # hand-built f-string here previously drifted from that
                        # key (used "cache:quote:{sym}" vs the real
                        # "quote:{sym}") and silently no-op'd every alert on
                        # every cycle — see workers/helpers/cache_publisher.py:38.
                        cache_key = cache_keys.quote(alert.symbol)
                        cached = r.get(cache_key)
                        if not cached:
                            # Visible-by-design: a persistent miss here means
                            # every ACTIVE alert for this symbol silently never
                            # fires. No retry/backfill added (out of scope) —
                            # this is observability only.
                            logger.warning(
                                "Alert check: no cached quote, skipping",
                                alert_id=alert.id,
                                symbol=alert.symbol,
                                cache_key=cache_key,
                            )
                            continue

                        quote = json.loads(cached)
                        price = quote.get("price", 0)
                        display_value = price

                        triggered = False
                        if alert_type_value == "PRICE_ABOVE" and alert.value and price > alert.value:
                            triggered = True
                        elif alert_type_value == "PRICE_BELOW" and alert.value and price < alert.value:
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
                            # bd:shotockviz-pls — routing key only: the
                            # broadcaster (main._dispatch_ws_message) sends
                            # alert_triggered ONLY to this user's sockets and
                            # strips user_id before delivery. Without it the
                            # message is dropped (fail closed).
                            "user_id": alert.user_id,
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
                    logger.info(
                        "Alert triggered",
                        alert_id=alert.id,
                        symbol=alert.symbol,
                        alert_type=alert_type_value,
                        display_value=display_value,
                    )

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
