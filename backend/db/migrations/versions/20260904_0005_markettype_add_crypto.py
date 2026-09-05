"""add CRYPTO value to markettype enum

bd:features-2026-09 slice B — schema change, expand-only on the existing
`stocks.market` native Postgres enum column. Source:
outputs/features-2026-09/09-sara-autopivot-crypto-spec.md §1.2.

NO MAGIC / self-discovering enum type name: the `stocks` table has never
gone through a migration (it was auto-created via `Base.metadata.create_all()`
since slice1 — see 09-sara-autopivot-crypto-spec.md §0 evidence table) and
`Enum(MarketType)` in models/stock.py does not pass `name=`, so no file in
this project states the real Postgres enum type name. Rather than hardcode
a guess (SQLAlchemy's undocumented default is the lowercase class name,
"markettype", but that is NOT verified against any real DB in this repo),
`upgrade()` looks it up at runtime via `information_schema.columns`
(table_name='stocks', column_name='market') → `udt_name`, then runs
`ALTER TYPE {udt_name} ADD VALUE IF NOT EXISTS 'CRYPTO'` against whatever
name is actually there. This is safe in any sandbox/dev/prod Postgres,
regardless of what the type happens to be called.

🔴 R1 FLAG — irreversible on Postgres. `ALTER TYPE ... ADD VALUE` cannot be
undone by `ALTER TYPE ... DROP VALUE` (Postgres has no such statement); the
only way back is DROP TYPE + rebuild + rewrite the column, which is out of
scope and not attempted here. This is an accepted one-way door for
dev/sandbox use (Tara approved). Per Sara's spec §1.2 / risk register R-1:
**apply to the prod DB (stockviz_prod) is BLOCKED pending explicit user
sign-off relayed by Oliver** — this migration file must not be run via
`alembic upgrade head` against prod until that sign-off happens.
`downgrade()` is an intentional no-op for this exact reason — do not
"fix" it into a fake DROP TYPE/rebuild; that would either silently no-op
in place (misleading) or destroy data (dangerous).

Revision ID: 20260904_0005
Revises: 20260904_0004
Create Date: 2026-09-04
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260904_0005"
down_revision: Union[str, None] = "20260904_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    # Discover the real enum type name for stocks.market — do NOT hardcode.
    udt_name = bind.execute(
        sa.text(
            "SELECT udt_name FROM information_schema.columns "
            "WHERE table_name = 'stocks' AND column_name = 'market'"
        )
    ).scalar()

    if not udt_name:
        raise RuntimeError(
            "stocks.market column not found via information_schema — "
            "cannot safely ALTER TYPE without knowing the real enum name. "
            "Refusing to guess (NO MAGIC)."
        )

    # ALTER TYPE ... ADD VALUE cannot run inside the same transaction as
    # other DDL/DML on PG < 12, but this migration has exactly one
    # statement, and PG 16 (per CLAUDE.md stack) supports it inside a
    # transaction anyway — see Sara's spec §1.2.
    op.execute(f"ALTER TYPE {udt_name} ADD VALUE IF NOT EXISTS 'CRYPTO'")


def downgrade() -> None:
    # Intentional no-op — see the R1 flag in the module docstring above.
    # Postgres has no `ALTER TYPE ... DROP VALUE`; removing 'CRYPTO' would
    # require DROP TYPE + recreate + rewrite the `stocks.market` column,
    # which is out of scope for this slice and not attempted here.
    pass
