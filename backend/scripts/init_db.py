#!/usr/bin/env python3
"""init_db.py — idempotent DB bootstrap for the GHCR/GHA deploy path.

Run inside the backend container, cwd /app (backend/Dockerfile:22 WORKDIR /app):
    python scripts/init_db.py

--- Root cause (bd deploy-gha-01, iter 2 live-run failure) ---------------------
Migration history only has two revisions:
  - 0001_ohlcv        (backend/db/migrations/versions/20260225_0001_ohlcv_bars.py)
      creates ONLY `ohlcv_bars` (+ TimescaleDB hypertable).
  - 20260302_0002     (backend/db/migrations/versions/20260302_0002_add_currency_to_transactions.py)
      ALTER TABLE transactions ADD COLUMN currency — assumes `transactions`
      already exists.
No migration ever CREATEs `users`, `transactions`, `stocks`, etc. Those tables
are only created via core/database.py:create_tables() (Base.metadata.create_all),
which main.py:204 runs ONLY when APP_ENV == "development". On a brand-new
production DB, `alembic upgrade head` therefore fails at 20260302_0002 with
psycopg2.errors.UndefinedTable: relation "transactions" does not exist.
(PRODUCTION_DEPLOY.md Step 5 already documents create_all as the first-deploy
fallback for exactly this reason — this script automates that fallback.)

--- Logic -----------------------------------------------------------------
FRESH database (no `users` table — `alembic_version` presence is IRRELEVANT,
see iter 2b note below):
  1. `alembic upgrade 0001_ohlcv` — the one thing plain create_all cannot do
     (create_hypertable() TimescaleDB call, see 20260225_0001_ohlcv_bars.py:36-42).
     No-op if the DB is already stamped/applied at 0001_ohlcv or later.
  2. `Base.metadata.create_all()` — creates every other table at model-head
     (transactions.currency is already in models/portfolio.py:28, so the
     resulting schema is equivalent to having run migration 20260302_0002).
  3. `alembic stamp head` — marks migration history as applied so future
     `alembic upgrade head` runs are genuine no-ops / real increments.
EXISTING database (`users` table already present):
  `alembic upgrade head` — normal incremental path.

--- iter 2b: why detection is `not has_users` only, not "no alembic_version
    AND no users" -----------------------------------------------------------
Real live-run state (bd deploy-gha-01) after the first failed deploy: the
FIRST iteration of this script's own `alembic upgrade 0001_ohlcv` step
already SUCCEEDED and left `alembic_version` = "0001_ohlcv" + `ohlcv_bars`
created, but `create_all()`/`stamp head` never ran because the process died
on that run before iter-2's fix existed — so the server is now in a state
that is neither "fully fresh" (alembic_version exists) nor "fully migrated"
(users/transactions don't exist). The original `not has_alembic_version and
not has_users` condition would misclassify this as "existing DB" and jump
straight to `alembic upgrade head`, hitting the exact same
UndefinedTable("transactions") failure again. `alembic upgrade 0001_ohlcv`
is idempotent/no-op when already at or past that revision, so re-running it
unconditionally whenever `users` is missing is safe and covers this
partially-migrated state too.

Exits non-zero on any failure (subprocess or Python exception) — never
silently "succeeds".
"""
import subprocess
import sys

sys.path.insert(0, "/app")  # backend/Dockerfile:22 WORKDIR /app; alembic.ini + models/ live here

from sqlalchemy import create_engine, text  # noqa: E402
from core.config import settings  # noqa: E402  — settings.sync_database_url, core/config.py:67-70


def log(msg: str) -> None:
    print(f"[init_db] {msg}", flush=True)


def run_alembic(*args: str) -> None:
    cmd = ["alembic", *args]
    log(f"$ {' '.join(cmd)}")
    subprocess.run(cmd, check=True, cwd="/app")


def table_exists(sync_engine, table_name: str) -> bool:
    with sync_engine.connect() as conn:
        result = conn.execute(text("SELECT to_regclass(:name)"), {"name": f"public.{table_name}"})
        return result.scalar() is not None


def create_all_tables() -> None:
    # Register every ORM model with Base.metadata before create_all().
    #
    # Deliberately broader than the brief's literal "copy import list from
    # create_tables()" instruction — evidence found two independent gaps in
    # the two EXISTING import lists in this repo:
    #   - core/database.py:44 create_tables() imports 7 modules — MISSING the
    #     5 V2 models (symbol_mapping, corporate_action, financial_history,
    #     earnings_event, document_embedding) that db/migrations/env.py:16-26
    #     already imports for autogenerate.
    #   - db/migrations/env.py:16-26 imports 11 modules — MISSING `ohlcv`
    #     (only ever imported by create_tables()) AND `note`
    #     (models/note.py:StockNote / stock_notes table, used by
    #     api/routes/notes.py:9, imported by NEITHER existing bootstrap path —
    #     a pre-existing gap, not introduced here; see artifact Open Questions).
    # `import models` pulls in models/__init__.py's 11-module aggregate;
    # ohlcv + note are added explicitly since neither list carries them.
    # create_all() is additive + checkfirst by default, so widening this list
    # cannot drop or alter any table that already exists.
    from core.database import Base
    import models              # noqa: F401 — User, Stock, Watchlist, Transaction, Alert, Drawing,
                                #              SymbolMapping, CorporateAction, FinancialHistory,
                                #              EarningsEvent, DocumentEmbedding (models/__init__.py:1-11)
    import models.ohlcv        # noqa: F401 — OHLCVBar (ohlcv_bars already exists via step 1; checkfirst skips it)
    import models.note         # noqa: F401 — StockNote (stock_notes) — not covered by any prior bootstrap path

    log("Base.metadata.create_all() — creating any table not yet present")
    sync_engine = create_engine(settings.sync_database_url)
    try:
        Base.metadata.create_all(bind=sync_engine)
    finally:
        sync_engine.dispose()


def main() -> None:
    sync_engine = create_engine(settings.sync_database_url)
    try:
        has_alembic_version = table_exists(sync_engine, "alembic_version")
        has_users = table_exists(sync_engine, "users")
    finally:
        sync_engine.dispose()

    log(f"alembic_version table present: {has_alembic_version}")
    log(f"users table present: {has_users}")

    if not has_users:
        # `users` missing covers both a fully-fresh DB AND a partially-migrated
        # one (e.g. alembic_version already at 0001_ohlcv from a prior failed
        # run — see iter 2b note in the module docstring). alembic_version's
        # presence is irrelevant to this branch; only `users` decides.
        log(
            "users table absent — FRESH or PARTIALLY-MIGRATED database, "
            "bootstrapping (upgrade 0001_ohlcv [no-op if already applied], create_all, stamp head)"
        )
        run_alembic("upgrade", "0001_ohlcv")
        create_all_tables()
        run_alembic("stamp", "head")
        log("Bootstrap complete.")
    else:
        log("users table present — fully migrated database, running normal incremental migration path")
        run_alembic("upgrade", "head")
        log("Migration complete.")


if __name__ == "__main__":
    try:
        main()
    except subprocess.CalledProcessError as exc:
        log(f"FAILED: {exc}")
        sys.exit(exc.returncode or 1)
    except Exception as exc:  # noqa: BLE001 — top-level script guard, must exit non-zero, never swallow
        log(f"FAILED: {exc!r}")
        sys.exit(1)
