"""Add ohlcv_bars table with TimescaleDB hypertable.

Revision ID: 0001_ohlcv
Revises:
Create Date: 2026-02-25
"""
from typing import Union
from alembic import op
import sqlalchemy as sa

revision: str = "0001_ohlcv"
down_revision: Union[str, None] = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ohlcv_bars",
        sa.Column("symbol",    sa.String(20),  primary_key=True, nullable=False),
        sa.Column("timeframe", sa.String(4),   primary_key=True, nullable=False),
        sa.Column("time_unix", sa.BigInteger(), primary_key=True, nullable=False),
        sa.Column("time_str",  sa.String(20),  nullable=False),
        sa.Column("open",      sa.Float(),     nullable=False),
        sa.Column("high",      sa.Float(),     nullable=False),
        sa.Column("low",       sa.Float(),     nullable=False),
        sa.Column("close",     sa.Float(),     nullable=False),
        sa.Column("volume",    sa.BigInteger(), nullable=False),
    )

    op.create_index("ix_ohlcv_sym_tf_ts",  "ohlcv_bars", ["symbol", "timeframe", "time_unix"])
    op.create_index("ix_ohlcv_sym_tf_str", "ohlcv_bars", ["symbol", "timeframe", "time_str"])

    # Convert to TimescaleDB hypertable partitioned on time_unix
    # Silently skips if TimescaleDB extension is not installed
    try:
        op.execute(
            "SELECT create_hypertable('ohlcv_bars', 'time_unix', "
            "chunk_time_interval => 2592000, if_not_exists => TRUE);"  # 30-day chunks
        )
    except Exception:
        pass  # Regular PostgreSQL without TimescaleDB — works fine, just no auto-partitioning


def downgrade() -> None:
    op.drop_table("ohlcv_bars")
