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

bd:shotockviz-rdu — the wall-clock cooldown above assumes the compared
value keeps changing on its own timescale, same as the level it's compared
against. That holds for an equity's live quote (re-fetched every ~1-6 min,
bd:shotockviz-cm3) but NOT for a Thai fund's NAV (bd:shotockviz-ubw's
`fund:{symbol}` fallback): `fund_fetcher` writes it once a day, 19:00 ICT,
T+1. A standing PRICE_ABOVE/PRICE_BELOW alert on a fund whose condition
becomes true stays true against that one unchanging number for the rest of
the day, and the 60-min cooldown alone re-fires it ~24 times for a single
crossing — the cooldown was never asked to also mean "the thing you're
being told about is actually new".

Fix, weighed against the AC's other option (refusing to arm price alerts
on fund symbols at creation): rejected that — it treats "the data source
happens to be daily" as a reason to withhold a feature the user asked for
(standing PRICE_ABOVE/PRICE_BELOW on any symbol they can watch), and funds
are a real, used part of this watchlist (25 active market=FUND symbols on
dev today). Chosen instead: `claim_alert()` takes an optional `value_ts` —
the compared value's own as-of (the `ts` already on every quote-shaped
dict: `cache_and_publish_quotes()` stamps it for equities,
`fund_payload_to_quote()` forwards fund_fetcher's stamp for funds) — and
ALSO requires it to be newer than the as-of of the data the alert last
fired on before a re-claim can win. This is additive to the wall-clock
cooldown, not a replacement, and it is NOT a second cooldown constant: it
has no duration of its own, just a strict "is this actually a new value"
check.

bd:shotockviz-wx3 corrected WHAT that check compares against. This bead
originally compared `value_ts` to `triggered_at` (when we fired), which
is only right because a quote's `ts` is roughly "now"; it is a coincidence
of that one data source, not a rule. The comparison is now against
`alerts.triggered_data_at` — the as-of of the data we fired on — so like
is compared with like. For equities, whose quote `ts` advances every fetch
cycle — far faster than the 60-min cooldown — this changes nothing
observable: by the time the cooldown elapses, the cached quote is always
newer than the last fire anyway (test_rdu_fund_nav_cooldown.py's
TestEquityAlertUnaffected proves this). For funds, it is the entire fix:
the same NAV can now win a claim at most once, and the next fetched NAV
(next day) is eligible again — see
test_rdu_fund_nav_cooldown.py::TestFundAlertRefiresAtMostOncePerNav.

bd:shotockviz-wx3 — the 5 indicator alert types (RSI Overbought/Oversold,
Golden/Death Cross, Volume Spike) are covered by the same rule now, and
they needed it more: they are used more than price alerts on funds, and
bd:shotockviz-1sf made them evaluate CLOSED bars only, so the value they
compare is a daily bar's derived indicator, which by construction does not
move intraday. An RSI alert that became true therefore stayed true and
re-notified once per 60-minute cooldown for the rest of the day, exactly
like the fund NAV case.

Their as-of is the closed bar's own timestamp (`_bar_value_ts` below), and
that is precisely why `claim_alert` compares against `triggered_data_at`
rather than `triggered_at`: a 1D bar dated 2026-09-04 read on 2026-09-06
is a date in the PAST, so `triggered_at < bar_ts` would be false from the
very first fire and would silently convert every indicator alert into
fire-once-forever — the one-shot behaviour bd:shotockviz-93h exists to
remove. `value_ts=None` remains the fallback for a source with no as-of at
all, and still means cooldown-only eligibility.
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

    if t in ("RSI_OVERBOUGHT", "RSI_OVERSOLD"):
        if alert.value is None:
            return False, 0.0
        rsi = indicators.compute_rsi(closes)
        # bd:shotockviz-032 — compute_rsi returns None (not 50.0) on
        # insufficient data since bd:shotockviz-kmi. `_MIN_BARS_FOR_INDICATORS`
        # (26) is comfortably above RSI's own minimum of period+1 = 15, so
        # this should be unreachable today — but the two numbers live in
        # different files and neither knows about the other, and comparing
        # None with `>` raises TypeError rather than returning a wrong
        # answer. Same guard shape as the GOLDEN_CROSS/DEATH_CROSS branch
        # below, which already treats an uncomputable indicator as
        # "cannot evaluate", not as a trigger.
        if rsi is None:
            return False, 0.0
        if t == "RSI_OVERBOUGHT":
            return rsi > alert.value, rsi
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
        # bd:shotockviz-032 — same reasoning as the RSI branch above.
        # compute_volume_ratio needs `lookback` (20) volumes and returns
        # None below that; it used to fall back to `vol_avg = 1`, which made
        # the "ratio" the raw share count and fired every VOLUME_SPIKE alert
        # unconditionally. Never compare that None.
        if ratio is None:
            return False, 0.0
        return ratio >= alert.value, ratio

    return False, 0.0


def _quote_value_ts(quote: dict) -> datetime | None:
    """Extract the compared value's own as-of from a quote-shaped dict.

    bd:shotockviz-rdu — `ts` is the epoch-second stamp already written by
    both producers of `quote:{symbol}`-shaped data: `cache_and_publish_
    quotes()` (equities — refreshed every fetch cycle) and
    `fund_payload_to_quote()` (funds — forwarded from `fund_fetcher`'s own
    stamp, refreshed once a day). Returns None when it's absent or
    unparseable, which callers treat as "no freshness signal available"
    and fall back to cooldown-only eligibility — the exact behaviour every
    alert had before this bead, never a hard failure.
    """
    ts = quote.get("ts")
    if ts is None:
        return None
    try:
        return datetime.fromtimestamp(float(ts), tz=timezone.utc)
    except (TypeError, ValueError, OSError, OverflowError):
        return None


def _bar_value_ts(bar: dict) -> datetime | None:
    """The closed bar's own as-of, for the 5 indicator alert types.

    bd:shotockviz-wx3 — sibling of `_quote_value_ts` above, and the reason
    `claim_alert` compares against `triggered_data_at` rather than
    `triggered_at`: this timestamp is a DATE IN THE PAST (a 1D bar dated
    2026-09-04 read on 2026-09-06), not a fetch time, so it is only
    comparable against another data as-of.

    Accepts either shape the cache has carried: `time_unix` (epoch seconds)
    when present, else the `time` string the daily payload actually uses
    today (`'2026-09-04'`, interpreted as UTC midnight — the bar's calendar
    date is what identifies it, and no intraday precision is needed to
    answer "is this a different bar from the one we fired on").

    Returns None on anything unparseable, which makes the caller fall back to
    cooldown-only eligibility rather than fail — the pre-bd behaviour.
    """
    raw = bar.get("time_unix")
    if raw is not None:
        try:
            return datetime.fromtimestamp(float(raw), tz=timezone.utc)
        except (TypeError, ValueError, OSError, OverflowError):
            return None

    raw = bar.get("time")
    if not isinstance(raw, str):
        return None
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def claim_alert(
    db,
    alert_id: int,
    value_ts: datetime | None = None,
    now: datetime | None = None,
) -> bool:
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

    `now` defaults to `datetime.now(timezone.utc)` when not given — the
    only caller in production (`check_all_alerts` below) never passes it,
    so this changes nothing there. It exists so tests can pin every
    timestamp this function reads and writes without depending on the
    real wall clock (bd:shotockviz-rdu) — see
    tests/test_rdu_fund_nav_cooldown.py::TestClaimAlertValueTsGate.

    `value_ts` (bd:shotockviz-rdu) — when given, ALSO requires it to be
    strictly newer than the alert's own `triggered_at` for the claim to
    win, on top of the wall-clock cooldown below. This is what stops a
    standing PRICE_ABOVE/PRICE_BELOW alert on a Thai fund re-firing once
    per cooldown against a NAV that has not actually changed (the fund's
    `ts` only advances once a day) — see the module docstring. `None`
    (the default, and every indicator-alert call today) disables this
    check entirely and reproduces the exact pre-bd behaviour: cooldown
    alone decides eligibility. Not a second cooldown constant — it has no
    duration of its own, only a freshness comparison against the same
    `triggered_at` column the cooldown already uses.

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

    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(minutes=settings.alert_cooldown_minutes)

    conditions = [
        Alert.id == alert_id,
        Alert.is_active == True,
        or_(Alert.triggered_at.is_(None), Alert.triggered_at <= cutoff),
    ]
    if value_ts is not None:
        # bd:shotockviz-wx3 — compare against `triggered_data_at` (the as-of
        # of the data we last fired on), NOT against `triggered_at` (when we
        # fired). bd:shotockviz-rdu used the latter, which happens to work
        # for quotes only because a quote's `ts` is roughly "now"; a closed
        # daily bar's timestamp is a date in the PAST, so that comparison is
        # false from the first fire and would make every indicator alert
        # fire once and never again — the exact bug bd:shotockviz-93h
        # existed to remove. Comparing like against like fixes both cases
        # with one rule instead of a per-type special case.
        conditions.append(
            or_(
                Alert.triggered_data_at.is_(None),
                Alert.triggered_data_at < value_ts,
            )
        )

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
        .where(*conditions)
        .values(
            status=AlertStatus.TRIGGERED,
            triggered_at=now,
            # bd:shotockviz-wx3 — written in the SAME atomic UPDATE that
            # claims the alert, so it can never drift from `triggered_at`
            # or from the number of notifications actually sent. Left
            # untouched when the caller has no freshness signal
            # (`value_ts=None`), rather than being clobbered with `now`,
            # which would fabricate an as-of the data never had.
            triggered_data_at=value_ts if value_ts is not None else Alert.triggered_data_at,
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
                    # bd:shotockviz-rdu / bd:shotockviz-wx3 — the compared
                    # value's own as-of. Set for BOTH families now: the
                    # quote/NAV `ts` for the price types, the closed bar's
                    # timestamp for the 5 indicator types. Stays None only
                    # when the source provides no as-of at all, which makes
                    # claim_alert() fall back to cooldown-only eligibility
                    # exactly as before these beads.
                    value_ts: datetime | None = None

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
                        # bd:shotockviz-wx3 — the indicator's value comes from
                        # the newest CLOSED bar (bd:shotockviz-1sf dropped the
                        # forming one), so that bar's own timestamp IS the
                        # as-of of the compared value. Without this an RSI or
                        # cross alert that became true stayed true against an
                        # unchanged daily bar and re-notified once per
                        # 60-minute cooldown for the rest of the day — the
                        # same defect bd:shotockviz-rdu fixed for fund NAVs,
                        # and on the more commonly used alert types.
                        value_ts = _bar_value_ts(bars[-1])
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
                            # bd:shotockviz-ubw — Thai fund NAVs stopped being
                            # dual-written into quote:{symbol}
                            # (bd:shotockviz-3ir), so a price alert on a fund
                            # must read fund:{symbol} itself or it would never
                            # fire again. The NAV is T+1 by design; see
                            # bd:shotockviz-rdu for the separate question of
                            # what a 60-minute alert cooldown means against a
                            # number that only changes once a day.
                            from services.fund_quote import fund_payload_to_quote

                            fund_quote = fund_payload_to_quote(
                                alert.symbol, r.get(cache_keys.fund(alert.symbol))
                            )
                            cached = json.dumps(fund_quote) if fund_quote else None
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
                        # bd:shotockviz-rdu — set for BOTH the live-quote
                        # and fund-fallback branches above: `quote` is the
                        # same quote-shaped dict either way, and both
                        # producers stamp `ts` (see _quote_value_ts).
                        value_ts = _quote_value_ts(quote)

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
                    won_claim = claim_alert(db, alert.id, value_ts=value_ts)

                    if not won_claim:
                        # bd:shotockviz-93h / bd:shotockviz-rdu — the old
                        # message here ("already claimed by ANOTHER run")
                        # stopped being accurate the moment claim_alert's
                        # guard grew a second, then a third, reason to
                        # refuse a claim: a concurrent run genuinely won
                        # the race (the original case this log existed
                        # for), OR THIS SAME alert already fired inside
                        # its own cooldown window, OR (rdu) the compared
                        # value hasn't advanced past the last fire (a
                        # fund's NAV, unchanged since it last notified) —
                        # cheap to tell apart (an extra query) but not
                        # worth it just to word a log line; naming all
                        # three possibilities is enough to not repeat this
                        # project's own documented failure mode of a
                        # message asserting something the code doesn't
                        # actually guarantee.
                        logger.info(
                            "Alert not claimed — still cooling down, value "
                            "unchanged since last fire, or already claimed "
                            "by a concurrent run this tick, skipping",
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
        # R1 (04-sara-telegram-spec.md §9) — 1 retry with short backoff;
        # a lost Telegram send after the DB commit is at-most-once and
        # accepted (outbox pattern is over-engineering for 1 user). Both the
        # retry and the dry-run guard now live in
        # services/telegram_notify.py (bd:shotockviz-4d9) — this must never
        # POST directly again, or dev regains the ability to page the user
        # from a laptop.
        from services.telegram_notify import send_telegram_message

        if send_telegram_message(
            user.telegram_chat_id, text, context="alert_checker"
        ):
            logger.info(
                "Telegram alert sent",
                alert_id=alert.id,
                symbol=alert.symbol,
                type=alert.alert_type.value,
                price=current_price,
                target=alert.value,
            )
        else:
            logger.error(
                "Failed to send Telegram alert after retry", alert_id=alert.id
            )
    except Exception as e:
        logger.error("Failed to send Telegram alert", error=str(e))
