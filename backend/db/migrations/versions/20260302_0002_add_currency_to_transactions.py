"""add currency to transactions

Revision ID: 20260302_0002
Revises: 20260225_0001
Create Date: 2026-03-02
"""
from alembic import op
import sqlalchemy as sa

revision = "20260302_0002"
down_revision = "20260225_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create enum type first
    currency_enum = sa.Enum("THB", "USD", name="currency")
    currency_enum.create(op.get_bind(), checkfirst=True)

    # Add column with default THB (backfills existing rows automatically)
    op.add_column(
        "transactions",
        sa.Column(
            "currency",
            sa.Enum("THB", "USD", name="currency"),
            nullable=False,
            server_default="THB",
        ),
    )


def downgrade() -> None:
    op.drop_column("transactions", "currency")
    sa.Enum(name="currency").drop(op.get_bind(), checkfirst=True)
