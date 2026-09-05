"""add nullable fx_rate to transactions

bd:shotockviz-fnn — the portfolio book normalises to THB. Until now the only
rate available was the *current* one (and a hardcoded 33.0 when even that was
missing), so a US position's cost and value were converted at the same rate and
the currency component of its THB return was structurally invisible.

This column stores THB per 1 unit of the transaction's own currency, observed
when the transaction is recorded (`api/routes/portfolio.py::add_transaction`).

Deliberately NULLABLE with **no backfill** — the user's decision, recorded on
the bead: historical rates are not reconstructed. A pre-existing row therefore
keeps `fx_rate IS NULL`, which the API reports as "FX return unavailable" for
that position instead of showing a number it does not have. Writing a guessed
rate into the ledger would be strictly worse than the bug being fixed.

THB rows need nothing: the base-currency rate is 1.0 by definition
(`services/portfolio_service.py::_txn_fx_rate`), so the entire existing Thai
book is FX-complete the moment this ships, with zero rows touched.

Non-destructive: ADD COLUMN ... NULL only. No rewrite, no default, no lock
beyond the catalog update — safe to run against prod with the app up.

Revision ID: 20260905_0007
Revises: 20260905_0006
Create Date: 2026-09-05
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260905_0007"
down_revision: Union[str, None] = "20260905_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # NO MAGIC / defensive existence check, same reasoning as 20260905_0006:
    # `transactions` was never created by a migration in this project (it exists
    # via Base.metadata.create_all() in core/database.py), so an Alembic-only
    # bootstrap can legitimately reach this revision without the table.
    exists = bind.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = 'transactions'")
    ).scalar()
    if not exists:
        print("[20260905_0007] transactions table not found — skipping")
        return

    already = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'transactions' AND column_name = 'fx_rate'"
        )
    ).scalar()
    if already:
        print("[20260905_0007] transactions.fx_rate already present — skipping")
        return

    op.add_column("transactions", sa.Column("fx_rate", sa.Float(), nullable=True))
    print("[20260905_0007] added transactions.fx_rate (nullable, not backfilled)")


def downgrade() -> None:
    bind = op.get_bind()
    exists = bind.execute(
        sa.text(
            "SELECT 1 FROM information_schema.columns "
            "WHERE table_name = 'transactions' AND column_name = 'fx_rate'"
        )
    ).scalar()
    if exists:
        op.drop_column("transactions", "fx_rate")
