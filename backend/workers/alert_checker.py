"""Celery task for checking price/indicator alerts.

bd:shotockviz-93h / bd:shotockviz-0ka (2026-09-06) — alerts are STANDING with
a cooldown, not one-shot. Previously `claim_alert()` set `is_active=False`
alongside `status=TRIGGERED` on every fire, which permanently removed the
alert from this task's selection query (`is_active==True AND
status==ACTIVE`) — nothing anywhere ever wrote `status` back to ACTIVE, so a
fired alert was spent and the only recovery was delete-and-recreate
(bd:shotockviz-0ka). That is now the design, not a bug: `is_active` stays
True through a fire (it is the user's own arm/pause control,
`PATCH /alerts/{id}/toggle` — untouched by this task), and re-eligibility is
governed by `triggered_at` + `settings.alert_cooldown_minutes` instead of by
`status`. See models/alert.py's `AlertStatus` docstring for what `status`
means now (a sticky "has this ever fired" flag, not a lifecycle gate).

RE-NOTIFY WHILE THE CONDITION STILL HOLDS, once cooldown expires: yes,
deliberately. A level crossed and held through a full cooldown window is a
later, separate event worth telling the trader about again — that is what
"standing" is FOR (a trader who wants exactly one notification per crossing,
ever, already has that: it is what one-shot used to do, and the user
rejected keeping that as the only mode). The cooldown itself is what absorbs
"crossed and held" vs "oscillating either side of a level" — see
core/config.py's `alert_cooldown_minutes` for the length reasoning. This task
does not additionally track "has price left the zone since last fire" before
allowing a re-fire: that would turn a standing alert back into a one-shot
with a timer (silent forever after the first fire unless price re-crosses),
which is the exact outcome the user's decision was written to avoid, and it
would need new persisted state (a "currently past threshold" flag) this
schema does not have and nothing in the brief asked for.
"""
from datetime import datetime, timedelta, timezone
from celery import shared_task
from core import cache_keys
from core.config import settings
from core.logger import get_logger
from services import indicators
# bd:shotockviz-1sf — reuse the exact per-symbol market-hours check
# workers/alert_symbol_refresher.py already uses (itself reused from
# workers/price_fetcher.py), so "is this market open right now" cannot
# drift between the three callers.
from workers.alert_symbol_refresher import _is_market_open_for

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


def _drop_forming_bar(symbol: str, bars: list[dict]) -> list[dict]:
    """Drop the last daily bar if `symbol`'s market is open right now.

    bd:shotockviz-1sf — the daily OHLCV cache's last bar is whatever
    session yfinance considers "today". While that market is open, that
    bar is still forming (its close/high/low/volume keep changing tick to
    tick), so a cross/RSI-threshold/volume-ratio computed against it can
    be TRUE right now and FALSE once the session actually closes. Under
    the standing+cooldown model (bd:shotockviz-93h) that is not a missed
    event (which a 1-day lag would be) — it is a FABRICATED one: the
    trader is told "RSI crossed above 70" for a cross that, at close,
    never happened. A late-by-a-day confirmed signal is an acceptable
    trade-off for a technical alert; a signal that describes an event
    which did not occur is not (it can drive a real trade off a
    non-event). So: exclude, don't flag-and-send — no UI disclaimer path
    was chosen here, unlike bd:shotockviz-cm3's *missed*-crossing case,
    because a false positive and a missed one are not symmetric harms.

    Once the market closes, that same bar IS the final, confirmed close
    for the day (yfinance stops revising it), so it is kept — this
    function only trims while the session is still live.
    """
    if not bars:
        return bars
    if _is_market_open_for(symbol, datetime.now(timezone.utc)):
        return bars[:-1]
    return bars


def _load_daily_bars(r, symbol: str) -> list[dict] | None:
    """Read the cached 1D OHLCV bars for `symbol`, or None on miss/short history.

    Mirrors the quote-cache-miss handling below: a miss here means every
    indicator-based alert for this symbol silently never fires until
    history_prefetcher warms the cache again — visible via the warning
    log, no retry/backfill added (same scope decision as the 983 fix).

    bd:shotockviz-1sf — the still-forming bar (see `_drop_forming_bar`) is
    dropped BEFORE the minimum-bars guard, so a symbol left with too few
    CLOSED bars is treated the same as "insufficient history" (skip, log,
    don't guess) rather than falling back to the partial bar.
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
    if not isinstance(bars, list):
        return None
    bars = _drop_forming_bar(symbol, bars)
    if len(bars) < _MIN_BARS_FOR_INDICATORS:
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
    """Atomically claim one eligible alert for triggering — the DB row IS
    the dedupe key (bd:features-2026-09 slice 3, Sara ADR-T3).

    Returns True iff THIS call won the claim (rowcount==1) — only the
    winner may send a notification. Commits on every call (both the win
    and the lose path) so the row lock is released immediately, matching
    Postgres's row-level locking semantics for concurrent UPDATEs on the
    same row: exactly one concurrent caller gets rowcount==1.

    Extracted as a standalone function (rather than inlined in
    `check_all_alerts`) so the race condition itself is unit-testable
    without needing Celery/Redis machinery — see
    tests/test_alert_checker_idempotency.py.

    bd:shotockviz-93h / bd:shotockviz-0ka — the WHERE guard changed from
    "never fired before" (`status==ACTIVE`) to "not fired recently"
    (never fired, OR fired outside the cooldown window) — see the module
    docstring for why. `is_active` is no longer written here: it is the
    user's own arm/pause control (`PATCH /alerts/{id}/toggle`) and a fire
    must not silently flip it, or a standing alert would go right back to
    behaving like one-shot.

    The cutoff (`now - cooldown`) is computed ONCE by the caller and
    passed in rather than each call re-deriving `now()` independently:
    two overlapping claims computing their own `now()` a few ms apart
    could otherwise let a losing claim's cutoff drift to just barely
    before the winner's freshly-committed `triggered_at`, defeating the
    dedupe. In production `check_all_alerts` calls this once per alert
    per tick with one shared `cutoff`, so this only matters for
    same-tick concurrency (the scenario this function's own tests
    exercise), not tick-to-tick cooldown timing.
    """
    from sqlalchemy import or_, update
    from models.alert import Alert, AlertStatus

    cutoff = datetime.now(timezone.utc) - timedelta(minutes=settings.alert_cooldown_minutes)

    # synchronize_session=False: this call only needs the row-level UPDATE's
    # rowcount, not an auto-refreshed in-memory `alert` object — the default
    # 'evaluate' strategy would otherwise re-run this WHERE clause in Python
    # against whatever Alert instance is already resident in `db`'s identity
    # map (check_all_alerts loads the alert into this same session before
    # calling claim_alert), comparing its already-loaded `triggered_at`
    # against `cutoff` as plain Python datetimes. That is harmless on
    # Postgres (TIMESTAMPTZ round-trips as tz-aware either way) but raises
    # `TypeError: can't compare offset-naive and offset-aware datetimes` on
    # SQLite in tests, whose DateTime type silently drops tzinfo on read —
    # found running this bead's own cooldown tests. Skipping the in-Python
    # re-evaluation entirely removes the discrepancy instead of papering
    # over it with tzinfo-stripping on one side.
    result = db.execute(
        update(Alert)
        .where(
            Alert.id == alert_id,
            Alert.is_active == True,
            or_(Alert.triggered_at.is_(None), Alert.triggered_at <= cutoff),
        )
        .values(
            status=AlertStatus.TRIGGERED,
            triggered_at=datetime.now(timezone.utc),
            trigger_count=Alert.trigger_count + 1,
        )
        .execution_options(synchronize_session=False)
    )
    db.commit()
    return result.rowcount == 1


@shared_task(bind=True, max_retries=3, default_retry_delay=60)
def check_all_alerts(self):
    """Check all active alerts and trigger notifications if conditions met.

    bd:shotockviz-93h — selection no longer filters on `status`: every
    is_active alert is standing and re-checked every tick, whether or not
    it has fired before. Alerts inside their cooldown window ARE still
    evaluated here (so the "no cached quote"/"no cached daily bars"
    observability logging below stays accurate for them too) but
    `claim_alert()` below will refuse the claim for one still cooling
    down, so it cannot re-notify early.
    """
    try:
        import redis
        import json
        from core.config import settings
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session
        from models.alert import Alert

        r = redis.from_url(settings.redis_url)

        # Use sync SQLAlchemy for Celery
        sync_url = settings.database_url.replace("+asyncpg", "")
        engine = create_engine(sync_url)

        with Session(engine) as db:
            alerts = db.execute(
                select(Alert).where(Alert.is_active == True)
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
                        # bd:shotockviz-93h — the old message here
                        # ("already claimed by ANOTHER run") stopped being
                        # accurate the moment claim_alert's guard grew a
                        # second reason to refuse a claim: it can lose
                        # because a concurrent run genuinely won the race
                        # (the original case this log existed for), OR
                        # because THIS SAME alert already fired inside its
                        # own cooldown window (the far more common case
                        # now that alerts are standing) — cheap to tell
                        # apart (an extra query) but not worth it just to
                        # word a log line; naming both possibilities is
                        # enough to not repeat this project's own
                        # documented failure mode of a message asserting
                        # something the code doesn't actually guarantee.
                        logger.info(
                            "Alert not claimed — still cooling down or already "
                            "claimed by a concurrent run this tick, skipping",
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
