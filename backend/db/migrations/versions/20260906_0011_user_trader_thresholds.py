"""add concentration_limit_pct + gap_min_pct to users (both nullable, additive)

bd:shotockviz-649.1 / bd:shotockviz-06z.1 — two trader-set thresholds that
used to live client-only (concentration limit: browser localStorage keyed
by user id) or not at all (gap-list minimum: bd:shotockviz-06z deliberately
shipped no magnitude filter). Both become real per-user server columns so
they follow the trader between devices, the same file/table
`telegram_chat_id` already lives on (20260904_0004_user_telegram_chat_id.py).

Purely additive, two nullable columns, no data read or written:
  * No backfill — every existing row gets NULL on both columns, which is
    the correct value for "never set one" (see models/user.py's docstring
    on why NULL is a distinct, meaningful state here, not "0" or a default
    number). A NULL cannot violate anything: there is no NOT NULL, no CHECK,
    no FK on either column.
  * No default at the DB layer, deliberately — a `server_default` would
    make "chose 25%" and "never touched the setting" both read back as
    25.0, exactly the ambiguity bd:shotockviz-649.1's acceptance criteria
    calls out ("a limit the user believes is saved and is not is worse
    than no limit"). The fallback each field uses when NULL is applied at
    the READ path instead (api/routes/portfolio.py,
    workers/gap_list_digest.py) — see those modules.
  * No CHECK constraint mirrored here, unlike telegram_chat_id's Postgres-
    only regex CHECK (0004). Bounds for both columns are plain numeric
    ranges (MIN_/MAX_CONCENTRATION_LIMIT_PCT in services/portfolio_service.py,
    MIN_/MAX_GAP_MIN_PCT in models/schemas.py) enforced at the sole write
    path (api/routes/settings.py, PATCH /settings/trader) — a DB-level
    CHECK would just be a second copy of the same range, and (per Float,
    not the telegram column's Postgres-only `~` operator) it COULD be
    written portably including in the SQLite test DB, but a duplicated
    bound is exactly the two-places-for-one-rule failure this codebase has
    already paid for (bd:4d9, bd:ubw) — so it is deliberately not restated
    here.
  * Production ran a fresh deploy earlier today (20260906_0010) and holds
    the trader's real rows — this migration never reads or rewrites a
    single one of them.

Revision ID: 20260906_0011
Revises: 20260906_0010
Create Date: 2026-09-06
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260906_0011"
down_revision: Union[str, None] = "20260906_0010"
branch_labels = None
depends_on = None


def _users_has_column(bind, column_name: str) -> bool:
    """NO MAGIC / defensive existence check, same reasoning as 0006-0010:
    `Base.metadata.create_all()` can also bring the `users` table (and, on
    a brand-new DB, this column) into existence ahead of Alembic ever
    running — a fresh create_all already has both new columns, so this
    migration must be a no-op there rather than fail on a duplicate
    ADD COLUMN."""
    return bool(
        bind.execute(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'users' AND column_name = :c"
            ),
            {"c": column_name},
        ).scalar()
    )


def upgrade() -> None:
    bind = op.get_bind()

    if not _users_has_column(bind, "concentration_limit_pct"):
        op.add_column(
            "users",
            sa.Column("concentration_limit_pct", sa.Float(), nullable=True),
        )
    if not _users_has_column(bind, "gap_min_pct"):
        op.add_column(
            "users",
            sa.Column("gap_min_pct", sa.Float(), nullable=True),
        )

    print(
        "[20260906_0011] users.concentration_limit_pct + users.gap_min_pct "
        "added, both NULL-default, nullable. No existing row changed."
    )


def downgrade() -> None:
    bind = op.get_bind()

    if _users_has_column(bind, "gap_min_pct"):
        op.drop_column("users", "gap_min_pct")
    if _users_has_column(bind, "concentration_limit_pct"):
        op.drop_column("users", "concentration_limit_pct")
