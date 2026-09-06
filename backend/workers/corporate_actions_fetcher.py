"""Celery worker: fetch corporate actions (dividends, splits) from Yahoo Finance.

Schedule: Daily at 02:00 ICT (19:00 UTC previous day)
Fetches dividend history and split events for all active symbols in the watchlist.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone

from celery import shared_task
from core.logger import get_logger
from core import cache_keys

logger = get_logger(__name__)


@shared_task(bind=True, max_retries=2, default_retry_delay=120)
def fetch_corporate_actions(self):
    """Fetch dividend and split data for all watched symbols.

    Iterates through all unique symbols from user watchlists and fetches
    dividend + split history from Yahoo Finance. Results are upserted into
    the corporate_actions table.
    """
    start = time.time()
    try:
        import redis
        from sqlalchemy import create_engine, text
        from core.config import settings

        redis_client = redis.from_url(settings.redis_url, decode_responses=True)
        engine = create_engine(settings.sync_database_url, pool_pre_ping=True)

        # Get all unique symbols from watchlists
        symbols = _get_watched_symbols(engine)
        if not symbols:
            logger.info("No symbols to fetch corporate actions for")
            return

        total_actions = 0
        errors = 0

        for symbol in symbols:
            try:
                count = _fetch_actions_for_symbol(symbol, engine, redis_client)
                total_actions += count
            except Exception as e:
                errors += 1
                logger.debug("Corporate action fetch failed", symbol=symbol, error=str(e))

        elapsed = time.time() - start
        logger.info(
            "Corporate actions fetch completed",
            symbols=len(symbols),
            total_actions=total_actions,
            errors=errors,
            elapsed_sec=f"{elapsed:.2f}",
        )

        # Update worker stats
        redis_client.set("worker:corporate_actions:last_success_at", datetime.now(timezone.utc).isoformat())
        redis_client.set("worker:corporate_actions:last_success_elapsed", f"{elapsed:.2f}")

    except Exception as exc:
        logger.error("fetch_corporate_actions failed", error=str(exc))
        try:
            redis_client.set("worker:corporate_actions:last_failure_at", datetime.now(timezone.utc).isoformat())
            redis_client.set("worker:corporate_actions:last_error", str(exc))
        except Exception:
            pass
        raise self.retry(exc=exc)


def _get_watched_symbols(engine) -> list[str]:
    """Get all unique symbols from watchlists + portfolio."""
    from sqlalchemy import text

    with engine.connect() as conn:
        result = conn.execute(text(
            "SELECT DISTINCT symbol FROM watchlist_items "
            "UNION "
            "SELECT DISTINCT symbol FROM transactions"
        ))
        return [row[0] for row in result.fetchall()]


# bd:shotockviz-eb1 — only these two alert types hold a PRICE. RSI_OVERBOUGHT /
# RSI_OVERSOLD hold an oscillator threshold, VOLUME_SPIKE a multiplier, and
# GOLDEN_CROSS / DEATH_CROSS hold nothing at all
# (workers/alert_checker.py::_evaluate_indicator_alert) — none of them is
# denominated in the stock's price, so none of them may be rebased. Scaling an
# RSI threshold of 70 by a split ratio would be pure nonsense.
_PRICE_ALERT_TYPES = ("PRICE_ABOVE", "PRICE_BELOW")


def rebase_price_alerts(conn, symbol: str, ex_date, ratio: float) -> int:
    """Restate price-alert levels set BEFORE `ex_date` into post-split units.

    bd:shotockviz-eb1. The one place in this codebase where a corporate action
    REWRITES a user row, and the asymmetry is deliberate:

      * A transaction is a RECORD OF A PAST EVENT. It must keep saying what the
        contract note says, so it is restated at read time and never written —
        `services/corporate_actions.py`.
      * An alert level is a STANDING INSTRUCTION ABOUT THE FUTURE. There is no
        past event to preserve. It is compared every 60 s
        (`workers/alert_checker.py`) against a live quote that is always in
        CURRENT units, and it is displayed to the user on the alerts screen. If
        the instruction is restated at read time instead, the checker and the
        screen show two different levels for the same alert — the exact
        two-surfaces-disagreeing failure bd:shotockviz-msg/-sbe/-la4 spent three
        beads unifying — and the checker (sync Celery) would need a second,
        synchronous reader of the corporate_actions table, which is the other
        thing this bead exists to avoid.

    So the level is rebased once, in place, at the moment the split is recorded,
    and `value_as_of` moves with it.

    IDEMPOTENCY. `value_as_of < ex_date` is the guard AND the effect: a rebased
    row has `value_as_of = ex_date`, so the daily re-run of this task over the
    same (unchanged) split table matches zero rows. This is what makes it safe
    for a task whose INSERT is `ON CONFLICT DO UPDATE` and therefore cannot
    distinguish a new split from one it has already seen a hundred times.

    NOT rebased, on purpose:
      * `value_as_of IS NULL` — units unknown, so no rebase can be justified.
        Declines instead of guessing (same doctrine as `transactions.fx_rate`).
      * `status = 'TRIGGERED'` — a fired alert is a historical record of what
        fired at what level, not a live instruction. Rewriting it would falsify
        the log. A *paused* alert (`is_active = false`, still `ACTIVE`) IS
        rebased: it will be re-armed later and must be right when it is.

    The original value is written to the log before it is overwritten — this
    task is the only writer and there is no alert-history table, so the log is
    the audit trail. Returns the number of rows rebased.
    """
    from sqlalchemy import text

    rebased = 0
    try:
        # SAVEPOINT. `conn` is the caller's live transaction, and the split rows
        # this task exists to record have already been INSERTed into it. Without
        # the nesting, one failing statement here (most likely
        # `alerts.value_as_of` not existing because migration 20260906_0008 has
        # not been applied) aborts that whole transaction, and the final
        # `conn.commit()` in `_fetch_actions_for_symbol` throws away the
        # corporate-action rows too — turning a skipped nice-to-have into data
        # loss on the table everything else depends on.
        with conn.begin_nested():
            # `alert_type` / `status` are Postgres ENUM columns and the bound
            # parameters arrive as text, so both are cast explicitly — an
            # untyped parameter compared against an enum is a driver-dependent
            # coin flip ("operator does not exist: alerttype = text"), not
            # something to leave to chance in a query that rewrites
            # money-adjacent user rows.
            rows = conn.execute(text(
                "SELECT id, value FROM alerts "
                "WHERE symbol = :symbol "
                "  AND alert_type::text IN (:type_above, :type_below) "
                "  AND value IS NOT NULL "
                "  AND value_as_of IS NOT NULL "
                "  AND value_as_of < :ex_date "
                "  AND status::text = 'ACTIVE'"
            ), {
                "symbol": symbol.upper(),
                "type_above": _PRICE_ALERT_TYPES[0],
                "type_below": _PRICE_ALERT_TYPES[1],
                "ex_date": ex_date,
            }).fetchall()

            for alert_id, old_value in rows:
                new_value = float(old_value) * ratio
                conn.execute(text(
                    "UPDATE alerts SET value = :new_value, value_as_of = :ex_date "
                    "WHERE id = :id"
                ), {"new_value": new_value, "ex_date": ex_date, "id": alert_id})
                # WARNING, not INFO: this is a silent-looking change to a number
                # the user typed themselves, and the pre-image exists nowhere
                # else — this log IS the audit trail.
                logger.warning(
                    "Alert level rebased for stock split",
                    alert_id=alert_id,
                    symbol=symbol.upper(),
                    ex_date=str(ex_date),
                    ratio=ratio,
                    old_value=float(old_value),
                    new_value=new_value,
                )
                rebased += 1
    except Exception as e:
        logger.warning(
            "Alert rebase skipped — alerts not updated for this split",
            symbol=symbol, ex_date=str(ex_date), error=str(e),
        )
        return 0

    return rebased


def _fetch_actions_for_symbol(symbol: str, engine, redis_client) -> int:
    """Fetch dividends and splits for a single symbol via yfinance."""
    import yfinance as yf
    from sqlalchemy import text
    from services.symbol_mapper import symbol_mapper

    yahoo_sym = symbol_mapper.get_yahoo_sync(symbol, redis_client)
    ticker = yf.Ticker(yahoo_sym)

    actions_count = 0

    # ── Dividends ────────────────────────────────────────────────────────────
    try:
        dividends = ticker.dividends
        if dividends is not None and not dividends.empty:
            with engine.connect() as conn:
                for idx, amount in dividends.items():
                    if amount and float(amount) > 0:
                        ex_date = idx.strftime("%Y-%m-%d")
                        conn.execute(text(
                            "INSERT INTO corporate_actions "
                            "(symbol, action_type, ex_date, value, source) "
                            "VALUES (:symbol, 'DIV', :ex_date, :value, 'yfinance') "
                            "ON CONFLICT ON CONSTRAINT uq_corp_action_symbol_type_date "
                            "DO UPDATE SET value = :value, source = 'yfinance'"
                        ), {
                            "symbol": symbol.upper(),
                            "ex_date": ex_date,
                            "value": round(float(amount), 6),
                        })
                        actions_count += 1
                conn.commit()
    except Exception as e:
        logger.debug("Dividend fetch failed", symbol=symbol, error=str(e))

    # ── Splits ───────────────────────────────────────────────────────────────
    try:
        splits = ticker.splits
        if splits is not None and not splits.empty:
            # bd:shotockviz-eb1 — collect and sort by ex-date ASCENDING before
            # writing. The alert rebase below is guarded by
            # `value_as_of < ex_date` and stamps `value_as_of = ex_date`, so two
            # splits applied newest-first would leave the older one permanently
            # skipped. yfinance happens to return this Series in ascending order;
            # the ordering is load-bearing, so it is enforced here rather than
            # assumed off a library's iteration order.
            rows = []
            for idx, ratio in splits.items():
                if ratio and float(ratio) != 1.0 and float(ratio) > 0:
                    # yfinance split ratio: "4.0" means 4:1 → our ratio = 1/4 = 0.25
                    rows.append((idx.date(), round(1.0 / float(ratio), 6)))
            rows.sort(key=lambda r: r[0])

            with engine.connect() as conn:
                for ex_date, split_ratio in rows:
                    conn.execute(text(
                        "INSERT INTO corporate_actions "
                        "(symbol, action_type, ex_date, ratio, source) "
                        "VALUES (:symbol, 'SPLIT', :ex_date, :ratio, 'yfinance') "
                        "ON CONFLICT ON CONSTRAINT uq_corp_action_symbol_type_date "
                        "DO UPDATE SET ratio = :ratio, source = 'yfinance'"
                    ), {
                        "symbol": symbol.upper(),
                        "ex_date": ex_date.isoformat(),
                        "ratio": split_ratio,
                    })
                    actions_count += 1
                    rebase_price_alerts(conn, symbol, ex_date, split_ratio)
                conn.commit()
    except Exception as e:
        logger.debug("Split fetch failed", symbol=symbol, error=str(e))

    # Invalidate adjusted price cache
    if actions_count > 0:
        try:
            redis_client.delete(f"corp_actions:{symbol.upper()}")
        except Exception:
            pass

    return actions_count
