"""Celery task: compute daily auto-pivot S/R levels for watched symbols.

bd:features-2026-09 slice A (auto-pivot) — 09-sara-autopivot-crypto-spec.md
§4.1-4.5, 06-tara-feature-scope.md ITEM 1 §1.3.

Pure functions live at module top (no DB/celery import inside them), same
testability pattern as srLevelColor.ts/syncSrPriceLines.ts on the frontend
side — deterministic, fixture-array testable, no DB needed. Algorithm
parameters (k=5 swing fractal, 1.0% cluster tolerance, ±0.25% dead band,
top-3 support + top-3 resistance) are Tara's domain call — do not deviate
without a spec revision.

Task shell below wires the pure functions to ohlcv_bars (read) and
sr_levels (write), and owns the guard/transaction logic.

G1 guard is PER-SIDE as of bd:features-2026-09 iter 7 — see
outputs/features-2026-09/13-tara-g1-guard-revision.md (supersedes the
"manual_import present -> skip whole symbol" behavior from
06-tara-feature-scope.md §1.3).
"""
from __future__ import annotations

from datetime import datetime, timezone

from celery import shared_task
from core.logger import get_logger
from workers.helpers.symbol_loader import get_watched_symbols

logger = get_logger(__name__)

# ── Tara §1.3 algorithm constants — do NOT deviate without a spec revision ──
FRACTAL_K = 5
CLUSTER_TOLERANCE = 0.010   # 1.0%, relative
DEAD_BAND = 0.0025          # ±0.25% around close — unclassifiable, discarded
TOP_N = 3                   # top-3 support + top-3 resistance = 6 rows max
MIN_BARS = 60                # G2 guard — fewer bars than this, skip symbol


# ─────────────────────────────────────────────────────────────────────────────
# Pure functions (unit-testable, deterministic, no I/O)
# ─────────────────────────────────────────────────────────────────────────────

def detect_fractals(bars: list[dict], k: int = FRACTAL_K) -> tuple[list[float], list[float]]:
    """Swing high/low fractal detection (Tara §1.3 step 1).

    `bars`: list of {"high": float, "low": float, ...} ordered ascending by
    time. A swing high at index i requires high[i] > high[j] for EVERY
    j in [i-k, i+k], j != i (strict `>` — ties are NOT pivots, this keeps
    the result deterministic and avoids double-counting a flat top).
    Symmetric for swing low with strict `<`.

    The first/last k bars can never have a full k-wide window on both
    sides, so they never confirm as a pivot — this is intentional
    (Tara §1.3: "an unconfirmed pivot is not tradeable").
    """
    n = len(bars)
    swing_highs: list[float] = []
    swing_lows: list[float] = []
    if n < 2 * k + 1:
        return swing_highs, swing_lows

    highs = [b["high"] for b in bars]
    lows = [b["low"] for b in bars]

    for i in range(k, n - k):
        window = range(i - k, i + k + 1)
        if all(highs[i] > highs[j] for j in window if j != i):
            swing_highs.append(highs[i])
        if all(lows[i] < lows[j] for j in window if j != i):
            swing_lows.append(lows[i])

    return swing_highs, swing_lows


def cluster_pivots(
    prices: list[float], tol: float = CLUSTER_TOLERANCE
) -> list[tuple[float, int]]:
    """Single-pass tolerance clustering (Tara §1.3 step 2).

    Sort ascending; a price joins the current cluster if it's within `tol`
    (relative — e.g. 0.010 = 1.0% — so the same code works for a ~35 THB
    stock and a ~180 USD stock) of that cluster's running mean; otherwise a
    new cluster opens. Returns [(cluster_mean, strength)] where
    strength = member count. Caller must pass swing-high and swing-low
    pools SEPARATELY (they mean different things and must not be merged
    into one cluster pool — Tara §1.3).
    """
    if not prices:
        return []

    ordered = sorted(prices)
    clusters: list[list[float]] = [[ordered[0]]]

    for p in ordered[1:]:
        current = clusters[-1]
        current_mean = sum(current) / len(current)
        if current_mean != 0 and abs(p - current_mean) / current_mean <= tol:
            current.append(p)
        else:
            clusters.append([p])

    return [(sum(c) / len(c), len(c)) for c in clusters]


def classify_and_select(
    clusters_hi: list[tuple[float, int]],
    clusters_lo: list[tuple[float, int]],
    close: float,
    top_n: int = TOP_N,
) -> list[dict]:
    """Classify vs `close`, tie-break, select top-N per side (Tara §1.3 steps 3-4).

    Classification is by relation to the current close, NOT by whether a
    cluster came from the swing-high or swing-low pool (an old swing high
    can end up below today's close and become support, and vice versa —
    this is intentional, per Tara §1.3):
      price < close * (1 - DEAD_BAND) -> support
      price > close * (1 + DEAD_BAND) -> resistance
      otherwise -> discarded (dead band, "would flip sides tomorrow")

    Selection within each side: sort by strength DESC, then
    |price - close| ASC, then price ASC (fully deterministic — no set/dict
    iteration order anywhere) -> take top `top_n`.

    Tag numbering ("AUTO S1".."AUTO S{top_n}" / "AUTO R1".."AUTO R{top_n}")
    is assigned AFTER selection, re-ordered by distance-from-close ascending
    (closest = 1) — a separate ordering from the strength-based selection
    above.
    """
    all_clusters = list(clusters_hi) + list(clusters_lo)
    candidates: list[dict] = []

    for price, strength in all_clusters:
        if price < close * (1 - DEAD_BAND):
            level_type = "support"
        elif price > close * (1 + DEAD_BAND):
            level_type = "resistance"
        else:
            continue  # dead band — not classifiable either way

        candidates.append({
            "price": price,
            "strength": strength,
            "level_type": level_type,
            "dist": abs(price - close),
        })

    def selection_key(c: dict) -> tuple:
        return (-c["strength"], c["dist"], c["price"])

    def top_for_side(side: str) -> list[dict]:
        return sorted(
            (c for c in candidates if c["level_type"] == side),
            key=selection_key,
        )[:top_n]

    selected_support = top_for_side("support")
    selected_resistance = top_for_side("resistance")

    rows: list[dict] = []
    for prefix, selected in (("S", selected_support), ("R", selected_resistance)):
        for idx, c in enumerate(sorted(selected, key=lambda c: c["dist"]), start=1):
            rows.append({
                "price": c["price"],
                "level_type": c["level_type"],
                "tag": f"AUTO {prefix}{idx}",
            })

    return rows


# ─────────────────────────────────────────────────────────────────────────────
# Task shell (DB/celery I/O)
# ─────────────────────────────────────────────────────────────────────────────

@shared_task(bind=True, max_retries=1, default_retry_delay=60)
def compute_auto_pivots(self):
    """Daily task: compute + write auto_pivot S/R levels for watched symbols.

    Beat schedule: crontab(hour=11, minute=0) UTC = 18:00 ICT
    (celery_app.py) — after SET close (16:30 ICT), before US open
    (21:30 ICT). No dirty-flag/recompute-avoidance by design (Tara: daily
    swing-pivot recompute on ~60 symbols x 126 bars is sub-second work;
    building a skip-if-unchanged mechanism for that would be
    over-engineering).

    Idempotent per symbol: DELETE-then-INSERT in one transaction, scoped
    STRICTLY to source='auto_pivot' — see _compute_and_write_symbol below,
    R0-adjacent (09-sara-autopivot-crypto-spec.md §2.4, risk R-2).
    """
    from sqlalchemy import create_engine
    from core.config import settings

    start = datetime.now(timezone.utc)
    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    symbols = get_watched_symbols(fallback=[])

    written = 0
    skipped = 0

    for symbol in symbols:
        try:
            result = _compute_and_write_symbol(engine, symbol)
            if result is None:
                skipped += 1
            else:
                written += result
        except Exception as e:
            logger.error("compute_auto_pivots symbol failed", symbol=symbol, error=str(e))
            skipped += 1

    elapsed = (datetime.now(timezone.utc) - start).total_seconds()
    logger.info(
        "compute_auto_pivots complete",
        total_symbols=len(symbols),
        rows_written=written,
        symbols_skipped=skipped,
        elapsed_sec=f"{elapsed:.2f}",
    )
    return {"total_symbols": len(symbols), "rows_written": written, "symbols_skipped": skipped}


def _compute_and_write_symbol(engine, symbol: str) -> int | None:
    """Compute + write auto_pivot rows for one symbol.

    Returns the number of rows written (0 is a valid, non-skip outcome —
    e.g. manual_import owns both sides), or None if the symbol was skipped
    by G2/G3 (never gets to the write path at all). G1 no longer skips the
    whole symbol — see per-side filtering below
    (outputs/features-2026-09/13-tara-g1-guard-revision.md §2).
    """
    from sqlalchemy import text

    with engine.connect() as conn:
        # G2 — need ohlcv_bars, and this doubles as the bar-count guard.
        bar_rows = conn.execute(
            text(
                "SELECT time_unix, high, low, close FROM ohlcv_bars "
                "WHERE symbol = :s AND timeframe = '1D' ORDER BY time_unix"
            ),
            {"s": symbol},
        ).fetchall()

    if len(bar_rows) < MIN_BARS:
        logger.debug("compute_auto_pivots: insufficient bars, skip", symbol=symbol, count=len(bar_rows))
        return None

    bars = [{"high": r.high, "low": r.low, "close": r.close} for r in bar_rows]
    close = bars[-1]["close"]

    # G3 — close sanity.
    if close is None or close <= 0:
        logger.debug("compute_auto_pivots: bad close, skip", symbol=symbol, close=close)
        return None

    swing_highs, swing_lows = detect_fractals(bars, k=FRACTAL_K)
    clusters_hi = cluster_pivots(swing_highs, tol=CLUSTER_TOLERANCE)
    clusters_lo = cluster_pivots(swing_lows, tol=CLUSTER_TOLERANCE)
    rows = classify_and_select(clusters_hi, clusters_lo, close, top_n=TOP_N)

    # G1 is checked HERE — at write time, in the SAME transaction as the
    # delete+insert below — not pre-filtered at task start, to keep the
    # race window against a concurrent manual import as narrow as possible
    # (09-sara-autopivot-crypto-spec.md §2.3). G1 is PER-SIDE as of iter 7
    # (13-tara-g1-guard-revision.md §2.1): a manual_import row on one side
    # blocks auto from writing THAT side only — the other side still gets
    # its normal auto refresh.
    with engine.begin() as conn:
        manual_has_support = conn.execute(
            text(
                "SELECT 1 FROM sr_levels WHERE symbol = :s AND source = 'manual_import' "
                "AND level_type = 'support' LIMIT 1"
            ),
            {"s": symbol},
        ).first() is not None
        manual_has_resistance = conn.execute(
            text(
                "SELECT 1 FROM sr_levels WHERE symbol = :s AND source = 'manual_import' "
                "AND level_type = 'resistance' LIMIT 1"
            ),
            {"s": symbol},
        ).first() is not None

        blocked = set()
        if manual_has_support:
            blocked.add("support")
        if manual_has_resistance:
            blocked.add("resistance")
        rows_to_write = [r for r in rows if r["level_type"] not in blocked]

        if blocked:
            logger.debug(
                "compute_auto_pivots: manual_import blocks side(s)",
                symbol=symbol,
                sides_blocked=",".join(sorted(blocked)),
            )

        # R0-adjacent — this DELETE must NEVER be broadened beyond
        # source='auto_pivot'. A wider WHERE here would destroy real
        # manual_import/user_created rows a user owns. Do not "simplify"
        # this clause. See 09-sara-autopivot-crypto-spec.md §2.4 / risk R-2,
        # and 13-tara-g1-guard-revision.md §3 (DELETE stays whole-symbol —
        # filtering happens on the INSERT side via rows_to_write above, not
        # by narrowing this WHERE).
        conn.execute(
            text("DELETE FROM sr_levels WHERE symbol = :s AND source = 'auto_pivot'"),
            {"s": symbol},
        )

        for row in rows_to_write:
            conn.execute(
                text(
                    "INSERT INTO sr_levels (symbol, price, level_type, tag, color, source, user_id) "
                    "VALUES (:symbol, :price, :level_type, :tag, NULL, 'auto_pivot', NULL)"
                ),
                {
                    "symbol": symbol,
                    "price": row["price"],
                    "level_type": row["level_type"],
                    "tag": row["tag"],
                },
            )

    return len(rows_to_write)
