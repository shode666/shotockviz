"""Remove `stocks` rows that today's registrar would refuse to write.

bd:shotockviz-ayz — cleanup for the data bd:shotockviz-m6q left behind.

WHAT IS WRONG
-------------
Before m6q, `workers/symbol_registrar._classify_market` resolved a bare symbol
that merely *starts with* a Thai fund-house prefix (SCB, TISCO, ASP, K-, B-, …)
to 'FUND' whenever yfinance had no confirmed live price for it. Several of those
are simultaneously real SET tickers, so a user who typed "TISCO" instead of
"TISCO.BK" got a `stocks` row claiming their SET equity is a mutual fund.

m6q fixed the classifier (it now answers 'AMBIGUOUS' and `_should_register`
refuses to write), but `register_symbol` short-circuits on
`SELECT id FROM stocks WHERE symbol = :symbol` — so a row written by the OLD
code is never revisited and will stay wrong forever. The fix cannot self-heal;
the row has to be removed. On the dev DB that is
`stocks.symbol='TISCO', market='FUND'`.

THE RULE THIS SCRIPT APPLIES
----------------------------
Delete exactly the rows the SHIPPED gate would refuse to create today:

    _should_register(_classify_market(symbol)) is False

i.e. the criterion is imported from the worker, not restated here — if the
classifier's idea of "ambiguous" ever changes, this script changes with it and
cannot drift into deleting something the app would happily write. `SCB.BK`
(SET), `K-CHINA` (FUND) and `AAPL` (US) are all things the gate accepts, so
they are never candidates.

WHY DELETE RATHER THAN CORRECT
------------------------------
There is no correct value to write: "TISCO" cannot be resolved to the SET equity
or to a fund without the user saying which (that is the whole of m6q). Deleting
returns the symbol to "unregistered", which is the state m6q intends — the row
stops asserting a wrong instrument, and `scan_unregistered` will re-offer it to
`register_symbol`, which will decline again, in the open, with a log line.

Nothing cascades: no table has a foreign key to `stocks.id` (verified — every
other table keys off the `symbol` string), so OHLCV/quote history is untouched.
The Redis `cache:name:{symbol}` entry written alongside the bad row IS cleared,
best-effort, because it would otherwise keep serving the wrong name for its
remaining TTL (86400 s).

SAFETY
------
* DRY RUN by default. Nothing is written without `--apply`.
* `--apply` REQUIRES `--expect-db <name>`, which is checked against
  `SELECT current_database()`. Point it at the wrong database and it aborts
  before touching anything. The dev database is `stockviz_db`
  (docker-compose.dev.yml:9); production is a different name and applying there
  is a human decision, not this script's.
* Idempotent: the criterion is a property of the row, so a second run finds no
  candidates and reports a no-op.

USAGE (inside the backend container, cwd /app — precedent: scripts/seed_history.py)

    # 1. look, change nothing
    docker-compose -f docker-compose.dev.yml exec -T backend \
        sh -c "cd /app && python -m scripts.purge_ambiguous_stock_rows"

    # 2. apply, on dev only
    docker-compose -f docker-compose.dev.yml exec -T backend \
        sh -c "cd /app && python -m scripts.purge_ambiguous_stock_rows \
               --apply --expect-db stockviz_db"

    # 3. re-run step 2 — must report 0 candidates (no-op)

Deliberately NOT an Alembic revision: a revision in the chain runs on the next
production deploy by itself, and whether these rows go on prod is a decision for
a human with the prod row list in front of them.
"""
from __future__ import annotations

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sqlalchemy import create_engine, text  # noqa: E402

from core import cache_keys  # noqa: E402
from core.config import settings  # noqa: E402
from workers.symbol_registrar import _classify_market, _should_register  # noqa: E402


def find_candidates(conn) -> list[dict]:
    """Rows the shipped registrar gate would refuse to write today."""
    rows = conn.execute(
        text("SELECT id, symbol, name, market FROM stocks ORDER BY symbol")
    ).fetchall()
    candidates = []
    for row in rows:
        symbol = row[1]
        # yf_info is deliberately None: the question is whether the SYMBOL ITSELF
        # is resolvable, which is what the row asserts. A live lookup here would
        # make the cleanup depend on whatever Yahoo answers this minute — and
        # m6q's evidence is that Yahoo's answer for a bare ambiguous symbol is
        # itself untrustworthy (see core/symbol_utils.py).
        market = _classify_market(symbol)
        if not _should_register(market):
            candidates.append(
                {"id": row[0], "symbol": symbol, "name": row[2],
                 "market": str(getattr(row[3], "value", row[3])),
                 "classified_now": market}
            )
    return candidates


def clear_name_cache(symbols: list[str]) -> None:
    """Best-effort: drop `cache:name:{symbol}` so the wrong name stops serving."""
    if not symbols:
        return
    try:
        import redis

        client = redis.from_url(settings.redis_url)
        for symbol in symbols:
            client.delete(cache_keys.name(symbol))
        print(f"  redis: cleared {len(symbols)} cache:name key(s)")
    except Exception as exc:  # never let a cache miss-fire undo a good DB run
        print(f"  redis: could NOT clear name cache ({exc}) — "
              f"stale names expire on their own within 24 h")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--apply", action="store_true",
                        help="actually delete (default: dry run, prints only)")
    parser.add_argument("--expect-db", metavar="NAME",
                        help="required with --apply; must equal current_database()")
    args = parser.parse_args()

    if args.apply and not args.expect_db:
        print("REFUSED: --apply requires --expect-db <name> (dev DB is "
              "'stockviz_db'). Naming the target is how this script cannot be "
              "pointed at production by accident.")
        return 2

    engine = create_engine(settings.sync_database_url, pool_pre_ping=True)
    with engine.connect() as conn:
        db_name = conn.execute(text("SELECT current_database()")).scalar()
        print(f"database: {db_name}")

        if args.apply and db_name != args.expect_db:
            print(f"REFUSED: connected to '{db_name}' but --expect-db said "
                  f"'{args.expect_db}'. Nothing was touched.")
            return 2

        candidates = find_candidates(conn)
        if not candidates:
            print("0 candidate row(s) — nothing to do (no-op).")
            return 0

        print(f"{len(candidates)} candidate row(s) — rows the registrar would "
              f"refuse to write today:")
        for c in candidates:
            print(f"  id={c['id']:<6} symbol={c['symbol']:<12} "
                  f"market={c['market']:<8} name={c['name']!r} "
                  f"-> classifies now as {c['classified_now']}")

        if not args.apply:
            print("\nDRY RUN — nothing written. Re-run with "
                  f"`--apply --expect-db {db_name}` to delete these rows.")
            return 0

        ids = [c["id"] for c in candidates]
        result = conn.execute(
            text("DELETE FROM stocks WHERE id = ANY(:ids)"), {"ids": ids}
        )
        conn.commit()
        print(f"\nDELETED {result.rowcount} row(s) from stocks in '{db_name}'.")
        clear_name_cache([c["symbol"] for c in candidates])
        print("Re-run this script: it must now report 0 candidates.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
