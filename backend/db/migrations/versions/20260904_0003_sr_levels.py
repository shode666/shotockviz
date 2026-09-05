"""add sr_levels table

bd:features-2026-09 slice 1 — schema only, additive (new table, no existing
table touched). Source: outputs/features-2026-09/00-sara-sr-schema.md §2.

Revision ID: 20260904_0003
Revises: 20260302_0002
Create Date: 2026-09-04
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260904_0003"
down_revision: Union[str, None] = "20260302_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "sr_levels",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("symbol", sa.String(20), nullable=False, index=True),
        sa.Column("price", sa.Float(), nullable=False),
        sa.Column("level_type", sa.String(10), nullable=False),
        sa.Column("tag", sa.String(50), nullable=True),
        sa.Column("color", sa.String(9), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual_import"),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            onupdate=sa.func.now(),
        ),
        sa.CheckConstraint("level_type IN ('support','resistance')", name="ck_sr_levels_level_type"),
        sa.CheckConstraint(
            "source IN ('manual_import','auto_pivot','user_created')",
            name="ck_sr_levels_source",
        ),
        sa.CheckConstraint("price > 0", name="ck_sr_levels_price_positive"),
    )
    op.create_index("ix_sr_levels_symbol_source", "sr_levels", ["symbol", "source"])


def downgrade() -> None:
    op.drop_index("ix_sr_levels_symbol_source", table_name="sr_levels")
    op.drop_table("sr_levels")
