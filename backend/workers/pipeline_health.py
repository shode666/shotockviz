"""Celery task: detect a stalled price-ingest pipeline and tell the user.

bd:shotockviz-5e7 — "nothing tells the user the data pipeline has died".
`/api/health` and `celery:stats:last_success_at` (backend/workers/__init__.py,
task_success signal) only prove SOME Celery task answered a ping; they do
not prove price_fetcher is actually writing fresh quotes. Worse, they
would stay green through the exact incident this bd is about: if
`yfinance_batch_quotes()` (price_fetcher.py) returns an empty dict for
every symbol (rate-limited, network blocked, endpoint shape changed —
all silent, none of them raise), `fetch_prices` still returns normally
with `priced: 0` — `task_success` fires, the global heartbeat stays
fresh, and every screen in the app keeps rendering yesterday's numbers
as if they were live. A signal built on "did the task raise" cannot see
this failure mode; a signal built on "is the cached data itself still
advancing" can, so that is what this module checks.

── Signal chosen: freshness of `quote:{symbol}` for price_fetcher's own
   always-on canaries ─────────────────────────────────────────────────
`workers/price_fetcher.py`'s round-robin (`fetch_prices`) tries its 6
market slots in order starting from a rotating index and returns at the
FIRST slot that is both open and has symbols to fetch. Two of those six
slots are gated on `_always` (`MARKET_SLOTS`: "Crypto" and "Overview" —
price_fetcher.py:120-127) instead of a market-hours function, and the
"Overview" slot's symbol list is the hardcoded, always-non-empty
`FALLBACK_IDX` (indices/FX/gold — price_fetcher.py:42-47), not the
watchlist. That means the attempt loop is *structurally* guaranteed to
find a successful slot within its own `NUM_SLOTS` (6) tries every single
invocation, market hours or not, weekday or weekend — worst case it
falls through SET/US/Asia/Europe/Crypto (all closed, or empty) and lands
on Overview, which always succeeds. So across any 6 consecutive 60s
`fetch-prices` beats, the newest `ts` among `FALLBACK_IDX`'s quote keys
is refreshed at least once — a worst-case gap of ~360s if `fetch_prices`
is actually running, with NO market-hours dependency at all.

That "no market-hours dependency" property is why this module does not
need `workers.sr_proximity_digest.is_trading_day_for_slot()` or
`workers.alert_symbol_refresher._is_market_open_for()` (the two existing
market-hours models, reviewed and deliberately not reused here): both
answer "is a specific market open", but the signal this task watches is
one price_fetcher itself keeps alive 24/7 by design, so there is no
weekend/holiday case where staleness here is expected — the FALLBACK_IDX
canaries never legitimately go quiet. `_is_market_open_for` is the
right thing to reuse if a future iteration adds PER-MARKET staleness
detection (e.g. "SET quotes specifically stopped advancing while SET is
open"); that is out of scope here (see STALE_THRESHOLD_SECONDS note
below) and filed as a follow-up, not silently skipped.

── Repeat / cooldown policy ─────────────────────────────────────────────
Edge-triggered + rate-limited reminder, composed from the two in-tree
precedents named in the ticket:
  - claim-before-notify (SETNX with a TTL) exactly like
    `sr_proximity_digest.send_sr_proximity_digest`'s run-lock: the FIRST
    stale check claims `_ALERT_LOCK_KEY` and sends; every check for the
    next `ALERT_COOLDOWN_SECONDS` fails the claim and sends nothing, so
    one ongoing outage does not become N messages.
  - `_DOWN_STATE_KEY` (no TTL, plain flag) tracks whether the pipeline is
    currently considered down, independent of the alert cooldown, so
    that on the FIRST check that sees fresh data again, exactly one
    recovery message goes out and both keys are cleared — clearing the
    lock on recovery (not just on TTL expiry) matters: without it, a
    brand-new outage that starts before the old cooldown window would
    have expired stays silently suppressed by the previous outage's lock.
  - A crash between claiming the lock and actually sending (DB error,
    process kill) is an accepted lost-notification trade-off, same as
    `sr_proximity_digest` documents for its own claim-before-send: an
    exactly-once delivery guarantee is out of scope for a monitoring
    alert whose own recheck cadence is 5 minutes.

── bd:shotockviz-5e7.1 — history and fundamentals ───────────────────────
bd:shotockviz-5e7 shipped the section above for price quotes only: neither
`ohlcv:{symbol}:{tf}` nor `fundamentals:{symbol}` carried a timestamp to
check. `workers/fundamentals_fetcher.py` and `workers/history_prefetcher.py`
(via `workers/helpers/cache_publisher.py`) now stamp a real server `ts`
on every successful write (see each file's own bd:shotockviz-5e7.1 comment
for the exact shape and what happens to keys already in Redis). That made
a real, non-inferred signal available for both — but "available" and
"safe to alert on" are different questions, answered separately below.

Fundamentals — ALERTED, same shape as price quotes above:
  `prefetch_fundamentals` (workers/fundamentals_fetcher.py) has NO
  cache-freshness gate at all — every scheduled run queries
  `FUNDAMENTALS_SYMBOLS_QUERY` fresh and attempts EVERY active,
  non-FUND/non-CRYPTO symbol, unconditionally. That is structurally the
  same "always advances if the task ran and yfinance answered at least
  once" property price_fetcher's Overview/Crypto canaries have — a
  trustworthy, MEASURED cadence, not an assumption: `celery_app.py:143`
  is `crontab(minute=15, hour="*/4")`, confirmed 4h apart, matching
  CLAUDE.md § Celery Workers. Worst-case healthy gap between two
  successful runs is exactly one cadence period (14400s) plus this
  task's own execution time; no profiling data exists for that
  execution time (ASSUMED, not measured), so the same qualitative
  "generous margin" policy as price's 1.7x is applied: +50% ->
  FUNDAMENTALS_STALE_THRESHOLD_SECONDS = 21600 (6h). Uses its own
  lock/down-state keys and message builders so a fundamentals outage and
  a price-quote outage are independent alerts with independent cooldowns.

History — DELIBERATELY NOT ALERTED, ts stamped for visibility only:
  `prefetch_history` (workers/history_prefetcher.py) fills COLD keys
  ONLY (`if redis_client.exists(cache_key): continue`) — there is no
  symbol it unconditionally refreshes every run the way price's
  Overview/Crypto slots or ALL of fundamentals's symbol set are. Its
  effective per-symbol refresh cadence is therefore the 6h cache TTL,
  not the 30-min beat, AND it is data-dependent: which symbol's cache
  happens to be cold at any given tick, not a fixed set. Two other
  writers this bd left out of scope
  (`services/cache_orchestrator.py`, `workers/on_demand_listener.py`)
  can keep a symbol's PRIMARY key warm indefinitely without ever
  touching the sibling `:ts` key `cache_and_publish_history()` writes —
  so in a deployment where those bypass paths happen to serve every
  watched symbol before its 6h TTL expires, history_prefetcher's own
  canary would legitimately go quiet FOREVER even though history data
  overall is fine, and that is indistinguishable, from this signal
  alone, from history_prefetcher having silently died (the exact CQRS
  failure mode `_fetch_symbol_history`'s swallowed exceptions can cause,
  same class as price's empty-dict case). Building a trustworthy
  threshold here would require giving history_prefetcher an
  unconditional-refresh canary the way price_fetcher has one
  (FALLBACK_IDX) — a real production-behavior change (extra yfinance
  calls every beat for whatever symbols are chosen), which is out of
  scope for a monitoring bd and is filed as a follow-up instead of
  silently smuggled in here. Per this bd's own instruction ("if a signal
  cannot be made non-noisy, leave it out and say why — a detector
  nobody trusts is worse than one that covers less"), `check_pipeline_
  health()` reports history's newest sibling-`ts` age as a DIAGNOSTIC
  value only (`result["history"]`, `is_stale` deliberately left `None`,
  `alerting: False`) — logged, returned, never pages anyone.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone

from celery import shared_task
from core import cache_keys
from core.logger import get_logger
from workers.price_fetcher import FALLBACK_IDX

logger = get_logger(__name__)

# Worst-case healthy gap for the FALLBACK_IDX canaries (see module
# docstring) is NUM_SLOTS(6) * the 60s fetch-prices beat = 360s. This is
# set to ~1.7x that so normal round-robin/beat jitter never trips a false
# alarm, while still catching a real outage inside ~2 check cycles.
STALE_THRESHOLD_SECONDS = 600  # 10 minutes

# How often `check-pipeline-health` runs (celery_app.py beat_schedule).
# Referenced here only for the reasoning above, not read at runtime.
CHECK_INTERVAL_SECONDS = 300  # 5 minutes

# Reminder cadence for an ongoing outage — long enough that a stalled
# pipeline does not become a wall of messages, short enough that a
# multi-hour outage is not silently ignored after the first alert.
ALERT_COOLDOWN_SECONDS = 3600  # 1 hour

_ALERT_LOCK_KEY = "lock:pipeline_health:price_quotes:alert"
_DOWN_STATE_KEY = "pipeline_health:price_quotes:down"

# bd:shotockviz-5e7.1 — see module docstring § "Fundamentals — ALERTED"
# for the full derivation: measured 14400s (4h) beat cadence
# (celery_app.py:143) + assumed 50% margin (no execution-time profiling
# available) = 21600s.
FUNDAMENTALS_STALE_THRESHOLD_SECONDS = 21600  # 6 hours

_FUNDAMENTALS_ALERT_LOCK_KEY = "lock:pipeline_health:fundamentals:alert"
_FUNDAMENTALS_DOWN_STATE_KEY = "pipeline_health:fundamentals:down"

# bd:shotockviz-5e7.1 — history's diagnostic-only threshold. NOT used to
# gate any alert (see module docstring § "History — DELIBERATELY NOT
# ALERTED"); kept only so `result["history"]["is_stale"]` has a
# consistent shape to leave `None` rather than omitting the key.


# ─────────────────────────────────────────────────────────────────────────────
# Pure functions (unit-testable, deterministic, no I/O)
# ─────────────────────────────────────────────────────────────────────────────

def _parse_ts(raw: bytes | str | None) -> int | None:
    """Extract the `ts` int stamped by `cache_and_publish_quotes()`
    (workers/helpers/cache_publisher.py:35). Anything unreadable is
    treated as "no data from this key" rather than raised — a single
    corrupt/legacy cache entry must not crash the health check."""
    if not raw:
        return None
    try:
        payload = json.loads(raw)
        ts = payload.get("ts")
        return int(ts) if ts is not None else None
    except (ValueError, TypeError, AttributeError):
        return None


def compute_staleness(
    raw_canary_quotes: list[bytes | str | None],
    now_ts: int,
    threshold_seconds: int = STALE_THRESHOLD_SECONDS,
) -> dict:
    """Pure staleness check over raw MGET results for the canary keys.

    `has_data=False` (no canary has ever been written, e.g. a fresh boot
    before warm-up) deliberately reads as NOT stale — that is the cold
    start covered by `/api/system/ready`, not an outage, and alerting on
    it would be exactly the "cries wolf" failure mode the ticket warns
    about (every fresh deploy would fire a false pipeline-down message).

    Boundary is `age > threshold` (strictly greater), not `>=`, so a
    canary refreshing exactly on the worst-case round-robin gap never
    flaps between healthy and stale on successive checks.
    """
    parsed = [_parse_ts(v) for v in raw_canary_quotes]
    valid = [t for t in parsed if t is not None]
    if not valid:
        return {"has_data": False, "newest_ts": None, "age_seconds": None, "is_stale": False}

    newest = max(valid)
    age = max(0, now_ts - newest)
    return {
        "has_data": True,
        "newest_ts": newest,
        "age_seconds": age,
        "is_stale": age > threshold_seconds,
    }


def _newest_ts(raw_values: list[bytes | str | None]) -> int | None:
    """Newest `ts` among raw cache values, or None if none parse.

    Same parsing as `compute_staleness()` (via `_parse_ts`) but without
    forcing a `threshold_seconds`/`is_stale` classification — used by the
    history diagnostic (bd:shotockviz-5e7.1), which deliberately reports
    only "how old is the newest signal we have", not a stale/not-stale
    verdict (see module docstring § "History — DELIBERATELY NOT ALERTED").
    """
    parsed = [_parse_ts(v) for v in raw_values]
    valid = [t for t in parsed if t is not None]
    return max(valid) if valid else None


def build_down_message(age_seconds: int) -> str:
    minutes = age_seconds // 60
    return (
        "🔴 ระบบดึงราคาหุ้นหยุดทำงาน\n"
        f"ราคาล่าสุดที่มีในระบบเก่ากว่า {minutes} นาทีแล้ว "
        "ตัวเลขที่เห็นในแอปตอนนี้อาจไม่ใช่ราคาปัจจุบัน"
    )


def build_recovered_message() -> str:
    return "✅ ระบบดึงราคาหุ้นกลับมาทำงานปกติแล้ว"


def build_fundamentals_down_message(age_seconds: int) -> str:
    hours = age_seconds // 3600
    return (
        "🔴 ระบบดึงข้อมูลพื้นฐาน (PE/PB/EPS) หยุดทำงาน\n"
        f"ข้อมูลล่าสุดที่มีในระบบเก่ากว่า {hours} ชั่วโมงแล้ว "
        "ตัวเลขพื้นฐานที่เห็นในแอปตอนนี้อาจไม่ใช่ข้อมูลล่าสุด"
    )


def build_fundamentals_recovered_message() -> str:
    return "✅ ระบบดึงข้อมูลพื้นฐานกลับมาทำงานปกติแล้ว"


# ─────────────────────────────────────────────────────────────────────────────
# Send helper (patterned after sr_proximity_digest._send_telegram_message —
# same (chat_id, text) shape, kept as a separate copy rather than an
# import because that function's own log lines name "sr proximity digest",
# which would be a misleading log for a pipeline-health alert)
# ─────────────────────────────────────────────────────────────────────────────

def _send_telegram_message(chat_id: str, text: str) -> bool:
    """Send one Telegram message. Delegates to the project's single outbound
    chokepoint (bd:shotockviz-4d9), which is what honours
    `settings.telegram_is_dry_run` — this function must never POST directly
    again, or dev regains the ability to page the user from a laptop.
    """
    from services.telegram_notify import send_telegram_message

    return send_telegram_message(chat_id, text, context="pipeline_health")
def _get_alert_recipients(db) -> list[tuple[int, str]]:
    """Active users with a Telegram chat id — same eligibility shape as
    `sr_proximity_digest`'s user query, minus the watchlist join (this is
    a global operational alert, not per-symbol)."""
    from sqlalchemy import select
    from models.user import User

    rows = db.execute(
        select(User.id, User.telegram_chat_id).where(
            User.telegram_chat_id.is_not(None),
            User.is_active == True,
        )
    ).all()
    return [(uid, chat_id) for uid, chat_id in rows]


def _get_fundamentals_canary_symbols(db) -> list[str]:
    """The exact symbol set `prefetch_fundamentals` attempts every run.

    bd:shotockviz-5e7.1 — imports the SAME named query constant
    `workers.fundamentals_fetcher.FUNDAMENTALS_SYMBOLS_QUERY` production
    runs (that constant's own comment: "named ... so tests can execute
    the EXACT query production runs"), rather than restating the
    is_active/market filter here and risking the two drifting apart.
    """
    from sqlalchemy import text
    from workers.fundamentals_fetcher import FUNDAMENTALS_SYMBOLS_QUERY

    rows = db.execute(text(FUNDAMENTALS_SYMBOLS_QUERY)).fetchall()
    return [r[0] for r in rows]


def _notify_all(text: str) -> None:
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from core.config import settings

    engine = create_engine(settings.sync_database_url)
    try:
        with Session(engine) as db:
            recipients = _get_alert_recipients(db)
    finally:
        engine.dispose()

    for _user_id, chat_id in recipients:
        _send_telegram_message(chat_id, text)


# ─────────────────────────────────────────────────────────────────────────────
# Task shell (Redis/DB/Celery I/O)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=2, default_retry_delay=60)
def check_pipeline_health(self, now_utc_iso: str | None = None):
    """Every `CHECK_INTERVAL_SECONDS`: check whether price_fetcher's
    always-on canary quotes are still advancing; alert on stale, alert
    once more on recovery.

    `now_utc_iso` is an injected clock (never passed by celery-beat —
    its call has no args), same pattern as
    `sr_proximity_digest.send_sr_proximity_digest(slot, now_utc_iso=...)`,
    so tests do not depend on wall-clock time.
    """
    import redis
    from core.config import settings

    utc_now = (
        datetime.fromisoformat(now_utc_iso).astimezone(timezone.utc)
        if now_utc_iso
        else datetime.now(timezone.utc)
    )
    now_ts = int(utc_now.timestamp())

    try:
        r = redis.from_url(settings.redis_url)
        raw_quotes = r.mget([cache_keys.quote(s) for s in FALLBACK_IDX])
        status = compute_staleness(raw_quotes, now_ts)

        if not status["has_data"]:
            logger.info("pipeline health: no canary quote data yet (cold start), skipping")
            return status

        if status["is_stale"]:
            logger.warning(
                "pipeline health: price quote pipeline looks stalled",
                age_seconds=status["age_seconds"],
            )
            claimed = r.set(_ALERT_LOCK_KEY, "1", nx=True, ex=ALERT_COOLDOWN_SECONDS)
            r.set(_DOWN_STATE_KEY, "1")
            if claimed:
                if settings.telegram_bot_token:
                    _notify_all(build_down_message(status["age_seconds"]))
                else:
                    logger.info("pipeline health: telegram not configured, alert not sent")
            else:
                logger.info("pipeline health: already alerted this cooldown window, skipping")
        else:
            was_down = r.get(_DOWN_STATE_KEY)
            if was_down:
                logger.info(
                    "pipeline health: price quote pipeline recovered",
                    age_seconds=status["age_seconds"],
                )
                r.delete(_DOWN_STATE_KEY)
                r.delete(_ALERT_LOCK_KEY)
                if settings.telegram_bot_token:
                    _notify_all(build_recovered_message())
                else:
                    logger.info("pipeline health: telegram not configured, recovery message not sent")

        # bd:shotockviz-5e7.1 — fundamentals (alerted) and history
        # (diagnostic only). Each wrapped in its OWN try/except: a DB or
        # Redis hiccup in either must not stop the price-quote result
        # above from being returned, and must not trip the outer
        # except/self.retry() below (which would needlessly re-run the
        # price section too — harmless given its own lock, but pointless).
        try:
            from sqlalchemy import create_engine
            from sqlalchemy.orm import Session
            from workers.helpers.symbol_loader import get_watched_symbols

            engine = create_engine(settings.sync_database_url)
            try:
                with Session(engine) as db:
                    fundamentals_symbols = _get_fundamentals_canary_symbols(db)
            finally:
                engine.dispose()

            if fundamentals_symbols:
                raw_fundamentals = r.mget([cache_keys.fundamentals(s) for s in fundamentals_symbols])
                fundamentals_status = compute_staleness(
                    raw_fundamentals, now_ts, threshold_seconds=FUNDAMENTALS_STALE_THRESHOLD_SECONDS,
                )
            else:
                fundamentals_status = {"has_data": False, "newest_ts": None, "age_seconds": None, "is_stale": False}
            status["fundamentals"] = fundamentals_status

            if fundamentals_status["has_data"]:
                if fundamentals_status["is_stale"]:
                    logger.warning(
                        "pipeline health: fundamentals pipeline looks stalled",
                        age_seconds=fundamentals_status["age_seconds"],
                    )
                    claimed = r.set(
                        _FUNDAMENTALS_ALERT_LOCK_KEY, "1", nx=True, ex=ALERT_COOLDOWN_SECONDS,
                    )
                    r.set(_FUNDAMENTALS_DOWN_STATE_KEY, "1")
                    if claimed:
                        if settings.telegram_bot_token:
                            _notify_all(build_fundamentals_down_message(fundamentals_status["age_seconds"]))
                        else:
                            logger.info("pipeline health: telegram not configured, fundamentals alert not sent")
                    else:
                        logger.info("pipeline health: fundamentals already alerted this cooldown window, skipping")
                else:
                    fundamentals_was_down = r.get(_FUNDAMENTALS_DOWN_STATE_KEY)
                    if fundamentals_was_down:
                        logger.info(
                            "pipeline health: fundamentals pipeline recovered",
                            age_seconds=fundamentals_status["age_seconds"],
                        )
                        r.delete(_FUNDAMENTALS_DOWN_STATE_KEY)
                        r.delete(_FUNDAMENTALS_ALERT_LOCK_KEY)
                        if settings.telegram_bot_token:
                            _notify_all(build_fundamentals_recovered_message())
                        else:
                            logger.info(
                                "pipeline health: telegram not configured, fundamentals recovery message not sent"
                            )

            # History — diagnostic only, see module docstring § "History —
            # DELIBERATELY NOT ALERTED". No lock/down-state keys, no
            # notify call: `is_stale` is intentionally left None rather
            # than computed against a threshold nobody can defend.
            watched_symbols = get_watched_symbols()
            if watched_symbols:
                from workers.helpers.cache_publisher import history_ts_key
                raw_history = r.mget(
                    [history_ts_key(cache_keys.ohlcv(s, "1D")) for s in watched_symbols]
                )
                newest_history_ts = _newest_ts(raw_history)
            else:
                newest_history_ts = None
            status["history"] = {
                "has_data": newest_history_ts is not None,
                "newest_ts": newest_history_ts,
                "age_seconds": (now_ts - newest_history_ts) if newest_history_ts is not None else None,
                "is_stale": None,
                "alerting": False,
            }
            logger.info("pipeline health: history diagnostic", **status["history"])

        except Exception as exc:
            logger.error("pipeline health: fundamentals/history check failed, skipping this cycle", error=str(exc))
            status.setdefault("fundamentals", {"has_data": None, "newest_ts": None, "age_seconds": None, "is_stale": None, "error": "check_failed"})
            status.setdefault("history", {"has_data": None, "newest_ts": None, "age_seconds": None, "is_stale": None, "alerting": False, "error": "check_failed"})

        return status

    except Exception as exc:
        logger.error("check_pipeline_health failed", error=str(exc))
        raise self.retry(exc=exc)
