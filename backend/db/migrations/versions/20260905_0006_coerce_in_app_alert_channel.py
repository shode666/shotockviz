"""coerce existing IN_APP alert channel rows to TELEGRAM

bd:shotockviz-675 — 'in_app' is being removed from the UI and from the
API's accepted values for new/updated alerts (no in-app notification
store exists; the only 'in_app' delivery was a best-effort 5s
react-hot-toast over a WebSocket that is dead in prod — see
docs/engagements/ui-honesty-2026-09.md, bd:shotockviz-suc). An alert
already stored with channel='IN_APP' must not become undeliverable AND
invisible after this ships.

Decision: coerce every existing IN_APP row to TELEGRAM. A TELEGRAM alert
whose user has no `telegram_chat_id` set is already a documented,
tested no-op (`workers/alert_checker.py::_send_telegram_alert` logs and
returns, does not error) — the same graceful "nothing happens" an IN_APP
row already had. So this coercion is a floor, never a regression: worst
case an affected row still delivers nothing (same as before); best case
it starts delivering via Telegram.

`AlertChannel.IN_APP` is intentionally NOT removed from the Python enum
(models/alert.py) or the Postgres `alertchannel` type by this migration —
kept so a row this migration does not reach (e.g. a restore applied
after this migration already ran) can still be *read* without the ORM
enum lookup crashing. `api/routes/alerts.py::_resolve_channel` is what
actually blocks 'in_app' going forward, independent of what the
Postgres enum type still permits.

NO MAGIC / defensive existence check: the `alerts` table itself was
never created by an Alembic migration in this project (verified —
`grep -rl alerts backend/db/migrations/versions/*.py` returns nothing;
`0001_ohlcv` is the base revision and only adds `ohlcv_bars`). It has
existed only via `Base.metadata.create_all()` (core/database.py,
dev-only) wherever this migration has actually been run so far. Guard
against a hypothetical Alembic-only bootstrap where `alerts` does not
exist yet, rather than hard-failing `alembic upgrade head`.

Revision ID: 20260905_0006
Revises: 20260904_0005
Create Date: 2026-09-05
"""
from typing import Union

from alembic import op
import sqlalchemy as sa

revision: str = "20260905_0006"
down_revision: Union[str, None] = "20260904_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()

    exists = bind.execute(
        sa.text("SELECT 1 FROM information_schema.tables WHERE table_name = 'alerts'")
    ).scalar()
    if not exists:
        print("[20260905_0006] alerts table not found — nothing to coerce, skipping")
        return

    result = bind.execute(
        sa.text("UPDATE alerts SET channel = 'TELEGRAM' WHERE channel = 'IN_APP'")
    )
    print(f"[20260905_0006] coerced {result.rowcount} IN_APP alert(s) to TELEGRAM")


def downgrade() -> None:
    # Intentional no-op — which specific rows were IN_APP before this ran
    # is not tracked, so there is no data-safe way to restore the
    # original value. Same accepted one-way-door class as
    # 20260904_0005's `ALTER TYPE ... ADD VALUE`.
    pass
