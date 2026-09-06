"""add nullable triggered_data_at to alerts

bd:shotockviz-wx3. `triggered_at` records WHEN we fired. This records the
as-of of the DATA we fired on — the quote/NAV `ts` for price alerts, the
closed bar's own timestamp for the 5 indicator types.

Why a new column rather than reusing one that exists:
  * `triggered_at` — bd:shotockviz-rdu compared it against the quote's `ts`
    directly, which works only because a quote's `ts` is roughly "now". A
    daily bar's timestamp is a date in the PAST, so `triggered_at < bar_ts`
    is false from the first fire and would turn every indicator alert into
    fire-once-forever — the exact bug bd:shotockviz-93h existed to remove.
  * `value_as_of` — already means something else entirely (bd:shotockviz-eb1:
    the trading units the user's threshold is stated in, the idempotency key
    for split rebasing). Overloading it would put two meanings in one field,
    which is the defect shape this engagement has spent the day removing.

Purely additive: one nullable timestamptz, no server default, no backfill.
NULL means "we have never recorded which data version we fired on", which the
claim guard treats as "no constraint" — so existing rows behave exactly as
they did before, and the column fills itself on the next fire.

Revision ID: 20260906_0012
Revises: 20260906_0011
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "20260906_0012"
down_revision: Union[str, None] = "20260906_0011"
branch_labels: Union[str, Sequence[str], None] = None
depends_on = None


def _alerts_has_column(bind, column_name: str) -> bool:
    """Same defensive existence check as migrations 0006-0011: a brand-new DB
    provisioned by `Base.metadata.create_all()` already has this column, so
    this migration must be a no-op there rather than fail on a duplicate
    ADD COLUMN."""
    return bool(
        bind.execute(
            sa.text(
                "SELECT 1 FROM information_schema.columns "
                "WHERE table_name = 'alerts' AND column_name = :c"
            ),
            {"c": column_name},
        ).scalar()
    )


def upgrade() -> None:
    bind = op.get_bind()
    if not _alerts_has_column(bind, "triggered_data_at"):
        op.add_column(
            "alerts",
            sa.Column("triggered_data_at", sa.DateTime(timezone=True), nullable=True),
        )
    print(
        "[20260906_0012] alerts.triggered_data_at added, nullable, no backfill. "
        "No existing row changed."
    )


def downgrade() -> None:
    bind = op.get_bind()
    if _alerts_has_column(bind, "triggered_data_at"):
        op.drop_column("alerts", "triggered_data_at")
