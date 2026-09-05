"""Celery task: Telegram digest of watchlist symbols near an S/R level.

bd:features-2026-09 iter 8 — 16-sara-sr-proximity-digest-spec.md.
Sends 2x/day per user (crontab in celery_app.py, slot arg identifies which):
"set_open" (09:30 ICT) and "us_premarket" (19:30 ICT). Pure functions
(compute_proximity_for_user, build_digest_message) live at module top —
no DB/celery import inside them, deterministic, fixture-testable without a
DB — same pattern as workers/sr_auto_pivot.py.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from celery import shared_task
from core.logger import get_logger

logger = get_logger(__name__)

# ── Constants (spec §4, §5, §8 — do not deviate without a spec revision) ──
PROXIMITY_PCT = 0.05  # 5%, inclusive (<=)
MAX_SYMBOLS_PER_MESSAGE = 20  # Telegram 4096-char limit guard (spec §4)
RUN_LOCK_TTL_SECONDS = 6 * 3600
SLOT_HEADERS = {
    "set_open": "ก่อน SET เปิด",
    "us_premarket": "ก่อน US pre-market",
}


# ─────────────────────────────────────────────────────────────────────────────
# Pure functions (unit-testable, deterministic, no I/O)
# ─────────────────────────────────────────────────────────────────────────────

def compute_proximity_for_user(
    watchlist_symbols: set[str],
    levels_by_symbol: dict[str, list[dict]],
    prices_by_symbol: dict[str, float],
    user_id: int,
    proximity_pct: float = PROXIMITY_PCT,
) -> list[dict]:
    """Return proximity matches for one user's watchlist (spec §3).

    `levels_by_symbol[symbol]` = list of {"price", "level_type", "tag",
    "user_id"} (already filtered to source IN manual_import/auto_pivot by
    the caller's SQL). Per-user scoping (level.user_id is NULL (global) OR
    == this user's id) is applied here, in-memory, per spec §3 Q2.

    Returns [{"symbol", "price", "matches": [{"level_type","price","tag",
    "distance_pct","signed_pct"}, ...]}] — matches sorted by distance_pct
    ascending, outer list sorted by each symbol's closest match ascending.
    """
    results: list[dict] = []
    for symbol in watchlist_symbols:
        price = prices_by_symbol.get(symbol)
        if price is None:
            continue  # no quote cached — skip symbol (spec §6)

        matches: list[dict] = []
        for level in levels_by_symbol.get(symbol, []):
            level_user_id = level.get("user_id")
            if level_user_id is not None and level_user_id != user_id:
                continue  # another user's private level — out of scope

            level_price = level["price"]
            if level_price <= 0:
                continue

            distance_pct = abs(price - level_price) / level_price
            if distance_pct > proximity_pct:
                continue

            signed_pct = (level_price - price) / level_price * 100
            matches.append({
                "level_type": level["level_type"],
                "price": level_price,
                "tag": level.get("tag"),
                "distance_pct": distance_pct,
                "signed_pct": signed_pct,
            })

        if matches:
            matches.sort(key=lambda m: m["distance_pct"])
            results.append({"symbol": symbol, "price": price, "matches": matches})

    results.sort(key=lambda r: r["matches"][0]["distance_pct"])
    return results


def build_digest_message(
    slot: str,
    proximity_results: list[dict],
    watchlist_count: int,
    today_str: str,
) -> str:
    """Build the Thai digest message text (spec §4)."""
    header_suffix = SLOT_HEADERS.get(slot, slot)

    if not proximity_results:
        return f"📊 วันนี้ไม่มีหุ้นใกล้ S/R ({header_suffix})"

    lines = [f"📊 สรุป S/R ใกล้ราคา — {header_suffix} ({today_str})", ""]

    shown = proximity_results[:MAX_SYMBOLS_PER_MESSAGE]
    for r in shown:
        lines.append(f"{r['symbol']}  {r['price']:.2f}")
        for m in r["matches"]:
            is_support = m["level_type"] == "support"
            emoji = "🟢" if is_support else "🔴"
            label = "แนวรับ" if is_support else "แนวต้าน"
            sign = "+" if m["signed_pct"] >= 0 else ""
            line = f"  {emoji} {label} {m['price']:.2f} ({sign}{m['signed_pct']:.1f}%)"
            if m.get("tag"):
                line += f" ({m['tag']})"
            lines.append(line)
        lines.append("")

    remaining = len(proximity_results) - len(shown)
    if remaining > 0:
        lines.append(f"…และอีก {remaining} ตัว")
        lines.append("")

    lines.append(f"รวม {len(proximity_results)} ตัว จาก watchlist {watchlist_count} ตัว")
    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Send helper (spec §4 — reuse alert_checker._send_telegram_alert's pattern
# but NOT the function itself: its signature is bound to an Alert object)
# ─────────────────────────────────────────────────────────────────────────────

def _send_telegram_message(chat_id: str, text: str) -> bool:
    """Send one Telegram message; 1 retry; never raises. Returns success bool."""
    import httpx
    from core.config import settings

    url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"

    last_error = None
    for _attempt in range(2):
        try:
            resp = httpx.post(url, json={"chat_id": chat_id, "text": text}, timeout=10)
            if resp.status_code == 200:
                logger.info("sr proximity digest sent", chat_id=chat_id)
                return True
            last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
        except httpx.HTTPError as e:
            last_error = str(e)

    logger.error("Failed to send sr proximity digest after retry", chat_id=chat_id, error=last_error)
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Task shell (DB/Redis/Celery I/O)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=2, default_retry_delay=120)
def send_sr_proximity_digest(self, slot: str):
    """Compute + send the S/R proximity digest for one beat slot.

    `slot` in {"set_open", "us_premarket"} — passed from beat args
    (celery_app.py), used for the dedupe lock key and message header.
    """
    from core.config import settings

    if not settings.telegram_bot_token:
        logger.info("Telegram bot token not configured, skipping sr proximity digest", slot=slot)
        return

    try:
        import json
        import redis
        from sqlalchemy import create_engine, select
        from sqlalchemy.orm import Session
        from models.user import User
        from models.watchlist import Watchlist, WatchlistItem
        from models.sr_level import SRLevel

        r = redis.from_url(settings.redis_url)

        # ICT date (UTC+7) — the 19:30 ICT slot crosses the UTC date boundary
        # (spec §5), so the lock key must use ICT's calendar date, not UTC's.
        ict_now = datetime.now(timezone.utc) + timedelta(hours=7)
        run_key = f"lock:sr_digest:{slot}:{ict_now.date().isoformat()}"

        # Claim BEFORE sending any message (spec §5) — at-most-once per
        # slot per ICT day. A lost send after a successful claim (task
        # crash mid-loop) is an accepted trade-off, same as
        # alert_checker.py's claim-before-notify design.
        if not r.set(run_key, "1", nx=True, ex=RUN_LOCK_TTL_SECONDS):
            logger.info("sr digest already ran for this slot today, skipping", slot=slot)
            return

        engine = create_engine(settings.sync_database_url)
        with Session(engine) as db:
            # Q1 — user + watchlist symbols, 1 round-trip. Users with no
            # chat_id or empty watchlist never appear in the result at all
            # -> skip silently by construction (spec §3, §6).
            rows = db.execute(
                select(User.id, User.telegram_chat_id, WatchlistItem.symbol)
                .join(Watchlist, Watchlist.user_id == User.id)
                .join(WatchlistItem, WatchlistItem.watchlist_id == Watchlist.id)
                .where(User.telegram_chat_id.is_not(None), User.is_active == True)
            ).all()

            users: dict[int, dict] = {}
            for user_id, chat_id, symbol in rows:
                entry = users.setdefault(user_id, {"chat_id": chat_id, "symbols": set()})
                entry["symbols"].add(symbol)

            if not users:
                logger.info("sr digest: no eligible users", slot=slot)
                return

            all_symbols = sorted({s for u in users.values() for s in u["symbols"]})

            # Q2 — S/R levels for every relevant symbol, 1 round-trip
            # (uses index ix_sr_levels_symbol_source).
            level_rows = db.execute(
                select(
                    SRLevel.symbol, SRLevel.price, SRLevel.level_type,
                    SRLevel.tag, SRLevel.user_id,
                ).where(
                    SRLevel.symbol.in_(all_symbols),
                    SRLevel.source.in_(["manual_import", "auto_pivot"]),
                )
            ).all()

            levels_by_symbol: dict[str, list[dict]] = {}
            for symbol, price, level_type, tag, level_user_id in level_rows:
                levels_by_symbol.setdefault(symbol, []).append({
                    "price": price,
                    "level_type": level_type,
                    "tag": tag,
                    "user_id": level_user_id,
                })

        # Q3 — current prices, 1 Redis MGET round-trip.
        prices_raw = r.mget([f"cache:quote:{s}" for s in all_symbols])
        prices_by_symbol: dict[str, float] = {}
        for symbol, raw in zip(all_symbols, prices_raw):
            if not raw:
                continue
            try:
                quote = json.loads(raw)
                prices_by_symbol[symbol] = quote["price"]
            except (ValueError, KeyError, TypeError) as e:
                logger.debug("sr digest: bad quote cache entry, skip symbol", symbol=symbol, error=str(e))

        today_str = ict_now.strftime("%d/%m")

        for user_id, entry in users.items():
            try:
                proximity = compute_proximity_for_user(
                    entry["symbols"], levels_by_symbol, prices_by_symbol, user_id,
                )
                message = build_digest_message(
                    slot, proximity, len(entry["symbols"]), today_str,
                )
                # Fail 1 user must not block the rest (spec §4/§6) —
                # _send_telegram_message itself never raises; this try/except
                # is the outer safety net for anything else in this block.
                _send_telegram_message(entry["chat_id"], message)
            except Exception as e:
                logger.error("sr proximity digest: failed for user", user_id=user_id, error=str(e))

    except Exception as exc:
        logger.error("sr proximity digest failed", slot=slot, error=str(exc))
        raise self.retry(exc=exc)
