"""widen sr_levels.level_type to allow 'stop' + require a stop to be user-owned

bd:shotockviz-43y — open risk needs a stop, and a stop needs somewhere to live.
It lives here: a `user_created` sr_levels row with `level_type='stop'`. The
argument for this table over a new one (there is no position entity; a holding
is a fold over `transactions`; a positions table would be a THIRD place a
price-per-symbol lives beside `alerts.value` and `sr_levels.price`) is in
models/sr_level.py's docstring.

Two constraint changes, both WIDENING or additive, no data is read or written:

  1. ck_sr_levels_level_type — 'support','resistance' -> plus 'stop'.
     A strict superset: every existing row still satisfies it, so the ALTER
     cannot fail on production data and no row changes.

  2. ck_sr_levels_stop_is_user_owned — NEW. `level_type <> 'stop' OR (source =
     'user_created' AND user_id IS NOT NULL)`. Vacuously true for every
     existing row (none is a stop), so it validates instantly against the rows
     the user's book already holds. It exists because scripts/import_sr_levels.py
     writes this table directly: without it, a curated import row (user_id NULL,
     returned to every caller including guests) could be written as a 'stop' and
     would then be read as somebody's stop-loss by anyone holding that symbol.

Deliberately NOT here:
  * No unique index on (user_id, symbol) for stops. One-stop-per-position is
    enforced on the write path (api/routes/sr_levels.py replaces in place), the
    same place bd:shotockviz-7ju puts its one-symbol-one-currency refusal, and
    the read path refuses to state a risk number if a second row ever appears
    (portfolio_service EXCLUDED_AMBIGUOUS_STOP). A partial index needs a
    per-dialect WHERE kwarg and the test suite runs SQLite against a Postgres
    production; an index that silently degraded to a NON-partial UNIQUE would
    forbid a user holding both a support and a resistance level on one symbol.
  * No backfill, no column added, no row rewritten. Production ran this
    morning's deploy and holds the user's real rows.

Downgrade narrows the type check back. It DELETES any 'stop' row first —
otherwise the narrowed constraint could not be validated. That deletion is the
only destructive statement in this file and it only ever removes rows this
revision made possible in the first place; it is announced in the log line.

Revision ID: 20260906_0010
Revises: 20260906_0009
Create Date: 2026-09-06
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260906_0010"
down_revision: Union[str, None] = "20260906_0009"
branch_labels = None
depends_on = None

_TYPE_CK = "ck_sr_levels_level_type"
_OWNED_CK = "ck_sr_levels_stop_is_user_owned"


def _sr_levels_exists(bind) -> bool:
    """NO MAGIC / defensive existence check, same reasoning as 0006-0009: tables
    in this project can also arrive via `Base.metadata.create_all()`, so an
    Alembic-only bootstrap can legitimately reach this revision without the
    table (and a fresh create_all already has the new constraints)."""
    return bool(
        bind.execute(
            sa.text(
                "SELECT 1 FROM information_schema.tables "
                "WHERE table_name = 'sr_levels'"
            )
        ).scalar()
    )


def _constraint_exists(bind, name: str) -> bool:
    return bool(
        bind.execute(
            sa.text(
                "SELECT 1 FROM information_schema.table_constraints "
                "WHERE table_name = 'sr_levels' AND constraint_name = :n"
            ),
            {"n": name},
        ).scalar()
    )


def upgrade() -> None:
    bind = op.get_bind()
    if not _sr_levels_exists(bind):
        print("[20260906_0010] sr_levels table not found — skipping")
        return

    # 1. Widen the level_type check. DROP IF EXISTS because a database
    #    bootstrapped by create_all() before 0003 existed may not carry the
    #    named constraint at all.
    op.execute(sa.text(f"ALTER TABLE sr_levels DROP CONSTRAINT IF EXISTS {_TYPE_CK}"))
    op.execute(
        sa.text(
            f"ALTER TABLE sr_levels ADD CONSTRAINT {_TYPE_CK} "
            "CHECK (level_type IN ('support','resistance','stop'))"
        )
    )

    # 2. A stop must be user-owned. Vacuously true for every existing row.
    if not _constraint_exists(bind, _OWNED_CK):
        op.execute(
            sa.text(
                f"ALTER TABLE sr_levels ADD CONSTRAINT {_OWNED_CK} CHECK ("
                "level_type <> 'stop' OR "
                "(source = 'user_created' AND user_id IS NOT NULL))"
            )
        )

    print(
        "[20260906_0010] sr_levels.level_type now allows 'stop'; stops are "
        "constrained to source='user_created' with a non-null user_id. "
        "No rows read or written."
    )


def downgrade() -> None:
    bind = op.get_bind()
    if not _sr_levels_exists(bind):
        return

    op.execute(sa.text(f"ALTER TABLE sr_levels DROP CONSTRAINT IF EXISTS {_OWNED_CK}"))

    # The narrowed check cannot be validated while 'stop' rows exist. Announced,
    # not silent — these are the only rows this revision made possible.
    result = bind.execute(sa.text("DELETE FROM sr_levels WHERE level_type = 'stop'"))
    print(f"[20260906_0010] downgrade deleted {result.rowcount} 'stop' level(s)")

    op.execute(sa.text(f"ALTER TABLE sr_levels DROP CONSTRAINT IF EXISTS {_TYPE_CK}"))
    op.execute(
        sa.text(
            f"ALTER TABLE sr_levels ADD CONSTRAINT {_TYPE_CK} "
            "CHECK (level_type IN ('support','resistance'))"
        )
    )
