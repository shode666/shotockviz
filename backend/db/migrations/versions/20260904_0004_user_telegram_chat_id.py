"""add telegram_chat_id to users

bd:features-2026-09 slice 3 — schema only, additive (nullable column on
existing table, no data migration/backfill needed). Source:
outputs/features-2026-09/04-sara-telegram-spec.md §4.

The CHECK constraint uses `~` (Postgres regex-match operator, no SQLite
equivalent) — this migration only ever runs against the real Postgres
DB (dev/prod), so that's fine here; it is deliberately NOT mirrored in
`models/user.py`'s ORM `__table_args__` because `Base.metadata.create_all()`
(backend/tests/conftest.py `test_db` fixture, in-memory SQLite) would fail
to create the `users` table entirely with that operator — see the
deviation note in `models/user.py` for the verified error.

Revision ID: 20260904_0004
Revises: 20260904_0003
Create Date: 2026-09-04
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260904_0004"
down_revision: Union[str, None] = "20260904_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("telegram_chat_id", sa.String(32), nullable=True),
    )
    op.create_check_constraint(
        "ck_users_telegram_chat_id_numeric",
        "users",
        "telegram_chat_id ~ '^-?[0-9]{1,20}$'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_users_telegram_chat_id_numeric", "users", type_="check")
    op.drop_column("users", "telegram_chat_id")
