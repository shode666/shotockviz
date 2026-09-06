"""Celery task: overnight-gap Telegram digest, scoped to one user's own book.

bd:shotockviz-06z — "trader: a 20:00 ICT pre-market gap list scoped to his
own book". He already checks US pre-market at 20:00 ICT (CLAUDE.md §
Stakeholder Context) one symbol at a time; this puts every symbol he holds
or watches in one message instead.

Reuses, does not reinvent:
  * `workers.sr_proximity_digest.is_trading_day_for_slot("us_premarket", ...)`
    — 20:00 ICT precedes the US session exactly like that module's existing
    19:30 ICT "us_premarket" slot (30 min earlier, same gate). Calling the
    SAME function with the SAME slot key is deliberate: the predicate this
    digest needs ("is there a US session about to open, judged in
    America/New_York's own calendar") is identical, not merely similar, so a
    second copy of the same weekday/timezone logic would be the exact
    "invented a second number for the same question" failure this codebase
    has been removing (see that module's CROSS_SOURCE_DEDUPE_TOLERANCE
    comment for the same principle applied to a price tolerance).
  * `services.portfolio_service.build_holdings` / `active_holdings` — "book"
    per the bd description is "the names he actually holds or watches", so
    holdings come from the ONE shared valuation fold, not a second hand-rolled
    read of `transactions`. Only the symbol set is needed here (no P&L), so
    `splits` is intentionally omitted from `build_holdings` — a stock split
    changes share count and price, never the symbol string, and this task
    never prices or sizes a position.
  * `services.fund_quote.fund_payload_to_quote` — bd:shotockviz-ubw: a
    consumer that reads only `quote:{symbol}` sees nothing at all for a Thai
    fund. See `_compute_gap_list` below for why a recovered fund quote is
    still excluded from the OUTPUT even though it is read.
  * The run-lock (claim-before-send SETNX, same as
    `sr_proximity_digest.send_sr_proximity_digest`) — this task fires from a
    single daily crontab entry, so it does not need
    `workers.pipeline_health`'s repeated-check cooldown (that pattern exists
    for a task re-evaluating live state every 5 minutes; this one runs once a
    day by schedule). The lock exists purely as a guard against a retried or
    manually re-triggered task producing a second message for the same ICT
    day — "one day, one message", not "one alert per outage".

── What "the gap" is, precisely, and how fresh it is at 20:00 ICT ──────────
`change_pct` in the cached `quote:{symbol}` payload IS the gap: it is
computed once, at fetch time, in `workers/price_fetcher.py`'s
`yfinance_batch_quotes()` as `(price - prev) / prev * 100`, where `price` is
yfinance's `fast_info.last_price` and `prev` is `fast_info.previous_close`
for that ticker. This module does not recompute it, look up a second
"previous close", or touch yfinance at all — reusing the one number every
other screen in this app already trusts as "today's change" is the honest
choice; inventing a second, differently-sourced "previous close" here would
risk disagreeing with the price the user sees everywhere else for the same
symbol.

Freshness is a *guarantee*, not an estimate: `quote:{symbol}` carries a 120s
TTL (`core/cache_keys.py::quote` docstring) and price_fetcher always writes
it with `setex`, so if the key is present at all, Redis itself proves it was
written within the last 120 seconds of the read — there is no code path that
lets a stale value silently outlive its TTL. At 20:00 ICT specifically
(`price_fetcher.py`'s round-robin slots `_set_hours`/`_asia_hours` are
already closed by then; `_us_hours`, `_eu_hours` and the always-on
Crypto/Overview slots are the ones still refreshing), a SET or Asia symbol in
the book will have had no writer for hours and its key will simply be gone —
not stale, absent. That absence is read as "no fresh quote for this symbol
right now" and the symbol is silently dropped from THIS digest (same
"no quote cached -> skip symbol" rule `sr_proximity_digest` already
documents for spec §6) rather than shown with an old number relabelled as a
live one. If EVERY symbol in a user's book comes back empty this way (e.g.
the whole book is Thai-only, or `fetch_prices` itself has not reached the US
slot yet this minute), `build_gap_list_message` says so explicitly instead
of sending nothing — see its docstring.

One honest limitation this module does NOT resolve: whether yfinance's
`fast_info.last_price` reflects an actual pre-market trade or is still
pinned to the prior regular-session print for a given ticker is an external
data-provider behaviour this codebase has never independently verified (no
test in this repo exercises it) — this task inherits that same uncertainty
every other `quote:{symbol}` consumer already carries, it does not introduce
a new one.

── What makes an entry worth listing ───────────────────────────────────────
There is no existing "notable move %" number anywhere in this codebase to
reuse. Checked: every threshold-shaped alert type (RSI_OVERBOUGHT/OVERSOLD,
VOLUME_SPIKE, PRICE_ABOVE/BELOW — `workers/alert_checker.py:127-142`) uses
`alert.value`, a USER-SUPPLIED number, explicitly documented as "NOT a
hardcoded 70" / "NOT a hardcoded 30". Inventing a global gap-% cutoff here
would break that same discipline for the same class of number. So this
digest applies NO magnitude filter: every symbol in the book with a fresh,
non-fund quote is included, ranked by `abs(change_pct)` descending (biggest
movers first — same "closest/most-actionable first" ordering
`sr_proximity_digest.compute_proximity_for_user` already uses), and capped
at `GAP_LIST_MAX_SYMBOLS_PER_MESSAGE` purely for Telegram's message-length
limit (same reasoning as that module's `MAX_SYMBOLS_PER_MESSAGE`), not as a
notability judgement. A per-user configurable minimum-gap setting, mirroring
`alert.value`, is the correct next step if noise turns out to be a real
problem in practice — filed as an open question, not guessed at here.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from celery import shared_task
from core.logger import get_logger
from workers.sr_proximity_digest import is_trading_day_for_slot

logger = get_logger(__name__)

# bd:shotockviz-06z — 20:00 ICT precedes the US session, same calendar as
# sr_proximity_digest's existing "us_premarket" slot (19:30 ICT, 30 min
# earlier). Reusing that slot KEY (not just the function) is deliberate:
# both ask the identical question ("is there a US session about to open,
# per America/New_York's own calendar").
_TRADING_DAY_SLOT = "us_premarket"

GAP_LIST_MAX_SYMBOLS_PER_MESSAGE = 20  # Telegram 4096-char guard — see module docstring
RUN_LOCK_TTL_SECONDS = 6 * 3600


# ─────────────────────────────────────────────────────────────────────────────
# Pure functions (unit-testable, deterministic, no I/O)
# ─────────────────────────────────────────────────────────────────────────────

def compute_gap_list(book_symbols: set[str], quotes_by_symbol: dict[str, dict | None]) -> list[dict]:
    """Return the overnight-gap rows for one user's book (spec: bd:shotockviz-06z).

    `quotes_by_symbol[symbol]` is the ALREADY-RESOLVED quote dict (the
    task shell does one batch `quote:{symbol}` MGET across every user's
    combined book plus the `fund:{symbol}` fallback for misses, exactly
    like `sr_proximity_digest.send_sr_proximity_digest` does — this
    function stays pure and per-user so it is fixture-testable without a
    DB or Redis).

    A symbol is included only if:
      - it has a quote at all (missing = no fresh price at this hour, see
        module docstring — skipped, never fabricated);
      - that quote is NOT `type == "fund_nav"` (bd:shotockviz-ubw's
        `fund_payload_to_quote` forces `change_pct=0.0` for every NAV,
        honestly, because a fund NAV has no intraday/pre-market gap
        concept at all — showing that forced zero here would misrepresent
        "not applicable" as "measured, unchanged", which is a fabrication
        of a different kind than a missing value);
      - `price` is a positive number and `change_pct` is present (same
        "no usable quote" doctrine as `portfolio_service.usable_price`).

    Sorted by `abs(change_pct)` descending — biggest movers first, no
    magnitude cutoff (see module docstring "What makes an entry worth
    listing").
    """
    results: list[dict] = []
    for symbol in book_symbols:
        quote = quotes_by_symbol.get(symbol)
        if not quote:
            continue  # no fresh quote cached at this hour — skip, do not fabricate

        if quote.get("type") == "fund_nav":
            continue  # NAV has no genuine gap concept — see docstring

        price = quote.get("price")
        change_pct = quote.get("change_pct")
        if price is None or change_pct is None:
            continue
        try:
            price = float(price)
            change_pct = float(change_pct)
        except (TypeError, ValueError):
            continue
        if price <= 0:
            continue

        results.append({"symbol": symbol, "price": price, "change_pct": change_pct})

    results.sort(key=lambda r: abs(r["change_pct"]), reverse=True)
    return results


def build_gap_list_message(results: list[dict], book_count: int, today_str: str) -> str:
    """Build the Thai digest message text.

    `book_count` is the size of the user's FULL book (watchlist ∪ open
    holdings), independent of how many of those symbols actually made it
    into `results`. When `results` is empty but `book_count > 0`, that gap
    (no pun intended) between "has a book" and "nothing priced" is reported
    explicitly — this is the "say so, report it" behaviour the bd calls for
    instead of substituting a number that looks right, or silently sending
    nothing (which would be indistinguishable from "the product ran and
    found no gaps", a false claim).
    """
    header = f"📊 Gap ข้ามคืน ก่อน US pre-market ({today_str})"

    if not results:
        return (
            f"{header}\n\n"
            f"ยังไม่มีราคาสดสำหรับหุ้น/กองทุนใน watchlist หรือพอร์ตของคุณตอนนี้ "
            f"(ทั้งหมด {book_count} รายการ) — อาจเป็นเพราะยังไม่ถึงรอบดึงราคาพรีมาร์เก็ต "
            f"ลองเปิดดูอีกครั้งในอีกไม่กี่นาที"
        )

    shown = results[:GAP_LIST_MAX_SYMBOLS_PER_MESSAGE]
    lines = [header, ""]
    for r in shown:
        is_up = r["change_pct"] >= 0
        emoji = "🟢" if is_up else "🔴"
        sign = "+" if is_up else ""
        lines.append(f"{emoji} {r['symbol']}  {r['price']:.2f}  ({sign}{r['change_pct']:.2f}%)")

    remaining = len(results) - len(shown)
    if remaining > 0:
        lines.append("")
        lines.append(f"…และอีก {remaining} ตัว")

    lines.append("")
    lines.append(f"มีราคาสด {len(results)} จาก {book_count} รายการใน watchlist/พอร์ตของคุณ")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Send helper (patterned after sr_proximity_digest._send_telegram_message —
# kept as a separate copy, not an import, because that function's log lines
# name "sr proximity digest", which would mislabel this task's sends)
# ─────────────────────────────────────────────────────────────────────────────

def _send_telegram_message(chat_id: str, text: str) -> bool:
    """Send one Telegram message. Delegates to the project's single outbound
    chokepoint (bd:shotockviz-4d9), which is what honours
    `settings.telegram_is_dry_run` — this function must never POST directly
    again, or dev regains the ability to page the user from a laptop.
    """
    from services.telegram_notify import send_telegram_message

    return send_telegram_message(chat_id, text, context="gap_list_digest")
# ─────────────────────────────────────────────────────────────────────────────
# Task shell (DB/Redis/Celery I/O)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=2, default_retry_delay=120)
def send_gap_list_digest(self, now_utc_iso: str | None = None):
    """Compute + send the overnight-gap digest for every eligible user.

    `now_utc_iso` is an injected clock (never passed by celery-beat — its
    `args` are empty, same as `pipeline_health.check_pipeline_health`), so
    tests never depend on the wall clock or the day of the week.
    """
    from core.config import settings

    utc_now = (
        datetime.fromisoformat(now_utc_iso).astimezone(timezone.utc)
        if now_utc_iso
        else datetime.now(timezone.utc)
    )

    # Cheapest gate first: no DB, no Redis, no run-lock claim on a day the
    # US session never opens (weekend). See module docstring for why this
    # reuses sr_proximity_digest's slot predicate directly.
    if not is_trading_day_for_slot(_TRADING_DAY_SLOT, utc_now):
        logger.info("gap list digest: not a US trading day, skipping")
        return

    if not settings.telegram_bot_token:
        logger.info("Telegram bot token not configured, skipping gap list digest")
        return

    try:
        import json
        import redis
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session
        from core import cache_keys
        from models.user import User
        from models.watchlist import Watchlist, WatchlistItem
        from models.portfolio import Transaction
        from services import portfolio_service
        from services.fund_quote import fund_payload_to_quote

        r = redis.from_url(settings.redis_url)

        # ICT date for the lock key — same reasoning as sr_proximity_digest:
        # a daily job's "already ran today" must be judged on ICT's calendar
        # date, not UTC's, since 20:00 ICT is only 13:00 UTC (same UTC day)
        # but a job running near midnight ICT would cross the UTC boundary.
        ict_now = utc_now + timedelta(hours=7)
        run_key = f"lock:gap_list_digest:{ict_now.date().isoformat()}"

        # Claim BEFORE sending, same at-most-once-per-day contract as
        # sr_proximity_digest's run-lock.
        if not r.set(run_key, "1", nx=True, ex=RUN_LOCK_TTL_SECONDS):
            logger.info("gap list digest already ran today, skipping")
            return

        engine = create_engine(settings.sync_database_url)
        with Session(engine) as db:
            eligible_rows = db.execute(
                select(User.id, User.telegram_chat_id).where(
                    User.telegram_chat_id.is_not(None), User.is_active == True
                )
            ).all()
            if not eligible_rows:
                logger.info("gap list digest: no eligible users")
                return
            eligible_ids = {uid for uid, _chat_id in eligible_rows}
            chat_id_by_user = dict(eligible_rows)

            watchlist_rows = db.execute(
                select(WatchlistItem.symbol, Watchlist.user_id)
                .join(Watchlist, WatchlistItem.watchlist_id == Watchlist.id)
                .where(Watchlist.user_id.in_(eligible_ids))
            ).all()
            watchlist_symbols_by_user: dict[int, set[str]] = {}
            for symbol, user_id in watchlist_rows:
                watchlist_symbols_by_user.setdefault(user_id, set()).add(symbol)

            # Ordered by date so build_holdings folds each user's lots
            # chronologically (its documented contract).
            txn_rows = db.execute(
                select(Transaction).where(Transaction.user_id.in_(eligible_ids)).order_by(Transaction.date)
            ).scalars().all()
            txns_by_user: dict[int, list] = {}
            for t in txn_rows:
                txns_by_user.setdefault(t.user_id, []).append(t)

            book_by_user: dict[int, set[str]] = {}
            for user_id in eligible_ids:
                watch = watchlist_symbols_by_user.get(user_id, set())
                # Symbol set only — splits are deliberately not applied
                # (module docstring): this task never prices or sizes a
                # position, only lists which symbols are currently open.
                holdings = portfolio_service.active_holdings(
                    portfolio_service.build_holdings(txns_by_user.get(user_id, []))
                )
                book = watch | set(holdings.keys())
                if book:
                    book_by_user[user_id] = book

            if not book_by_user:
                logger.info("gap list digest: no user has a non-empty book")
                return

            all_symbols = sorted({s for book in book_by_user.values() for s in book})

        # One batch MGET across every eligible user's combined book —
        # same "no N+1" design as sr_proximity_digest.
        prices_raw = r.mget([cache_keys.quote(s) for s in all_symbols])

        # bd:shotockviz-ubw fallback for symbols that missed the quote MGET
        # (a Thai fund never writes quote:{symbol}, see fund_quote.py).
        fund_misses = [s for s, raw in zip(all_symbols, prices_raw) if not raw]
        if fund_misses:
            fund_raw = r.mget([cache_keys.fund(s) for s in fund_misses])
            recovered = {
                s: json.dumps(q)
                for s, q in (
                    (s, fund_payload_to_quote(s, raw))
                    for s, raw in zip(fund_misses, fund_raw)
                )
                if q is not None
            }
            prices_raw = [
                raw if raw else recovered.get(s)
                for s, raw in zip(all_symbols, prices_raw)
            ]

        quotes_by_symbol: dict[str, dict | None] = {}
        for symbol, raw in zip(all_symbols, prices_raw):
            if not raw:
                quotes_by_symbol[symbol] = None
                continue
            try:
                quotes_by_symbol[symbol] = json.loads(raw)
            except (ValueError, TypeError) as e:
                logger.debug("gap list digest: bad quote cache entry, skip symbol", symbol=symbol, error=str(e))
                quotes_by_symbol[symbol] = None

        today_str = ict_now.strftime("%d/%m")

        for user_id, book in book_by_user.items():
            try:
                results = compute_gap_list(book, quotes_by_symbol)
                message = build_gap_list_message(results, len(book), today_str)
                # One user's failure must not block the rest —
                # _send_telegram_message itself never raises; this
                # try/except is the outer safety net for anything else.
                _send_telegram_message(chat_id_by_user[user_id], message)
            except Exception as e:
                logger.error("gap list digest: failed for user", user_id=user_id, error=str(e))

    except Exception as exc:
        logger.error("gap list digest failed", error=str(exc))
        raise self.retry(exc=exc)
