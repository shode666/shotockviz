"""add nullable value_as_of to alerts

bd:shotockviz-eb1 — an alert level is a price, and a stock split changes the
units prices are quoted in. After a 2:1 split an untouched "notify me above 100"
fires the instant the market reopens at 50, because the level was set in old
units and `alert_checker` compares it against a live quote that is always in new
ones.

Rebasing that level needs to know WHICH UNITS IT IS IN, and the alerts table did
not record that. Neither existing timestamp can stand in:

  created_at — too early. `PUT /alerts/{id}` changes `value` without touching
    created_at (api/routes/alerts.py:131-137), so a level the user had already
    re-entered in post-split units would be rebased a second time — turning a
    currently-CORRECT alert into a wrong one. Strictly worse than the bug.
  updated_at — too late. `onupdate=func.now()` fires on any write, including
    `PATCH /alerts/{id}/toggle`, which does not touch `value` at all.

So: one new column, written whenever `value` is written.

BACKFILL — `updated_at::date`, deliberately, and this direction is chosen because
its failure mode is one-sided. `updated_at >= created_at` always, so the backfill
can only ever be LATER than the true units date. Too late means "no rebase" =
exactly today's behaviour for that row (the pre-existing bug, unchanged). Too
early would mean rebasing a level that is already correct = a NEW wrong number in
a money-adjacent path. When in doubt about user data, decline. `created_at` is
used only for rows where `updated_at` is somehow NULL.

Non-destructive: ADD COLUMN ... NULL, then a single UPDATE that writes ONLY the
new column. No existing column is read-modify-written; `alerts.value` is not
touched by this migration at all (the rebase itself lives in
workers/corporate_actions_fetcher.py and is guarded by `value_as_of < ex_date`,
which makes it idempotent across the daily re-run).

Revision ID: 20260906_0008
Revises: 20260905_0007
Create Date: 2026-09-06
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260906_0008"
down_revision: Union[str, None] = "20260905_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # NO MAGIC / defensive existence check, same reasoning as 20260905_0006 and
    # _0007: `alerts` was never created by a migration in this project (it exists
    # via Base.metadata.create_all() in core/database.py — see the DB enum note
    # in models/alert.py), so an Alembic-only bootstrap can legitimately reach
    # this revision without the table.
    exists = bind.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = 'alerts'")
    ).scalar()
    if not exists:
        print("[20260906_0008] alerts table not found — skipping")
        return

    already = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'alerts' AND column_name = 'value_as_of'"
        )
    ).scalar()
    if already:
        print("[20260906_0008] alerts.value_as_of already present — skipping")
        return

    op.add_column("alerts", sa.Column("value_as_of", sa.Date(), nullable=True))

    # Conservative backfill — see the module docstring. COALESCE only so a row
    # with a NULL updated_at (possible for rows written before the server_default
    # existed) still gets the only other recorded write date it has.
    result = bind.execute(
        sa.text(
            "UPDATE alerts "
            "SET value_as_of = COALESCE(updated_at, created_at)::date "
            "WHERE value_as_of IS NULL "
            "  AND COALESCE(updated_at, created_at) IS NOT NULL"
        )
    )
    print(
        f"[20260906_0008] added alerts.value_as_of; backfilled {result.rowcount} row(s) "
        "from updated_at::date (conservative: can only under-rebase, never over-rebase)"
    )


def downgrade() -> None:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'alerts' AND column_name = 'value_as_of'"
        )
    ).scalar()
    if exists:
        op.drop_column("alerts", "value_as_of")
